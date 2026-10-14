using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace OxpInstaller;

public static partial class PartitionDeploymentChecks
{
    public static async Task CrashWriterAsync(string imagePath, string directory, InstallationTargetKind kind)
    {
        directory = Path.GetFullPath(directory);
        MediaSource.Ordinary(Path.Combine(directory, "media.vhd"), InstallerWorkspace.DirectoryPath, false);
        if (!System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(directory), "^partition-deploy-[0-9a-f]{32}$"))
            throw new IOException("Crash test requires a new owned partition fixture.");
        using var image = new PreparedDiskImage(imagePath);
        using var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size);
        OwnedPartitionLayout.Initialize(disk, image.Layout, kind == InstallationTargetKind.InternalShared ? image.Layout.Protected : []);
        using var frozen = kind == InstallationTargetKind.InternalShared ? await SeedProtectedAsync(image, disk) : null;
        await PartitionDeployment.ApplyOwnedAsync(image, disk, kind, Path.Combine(directory, "state.json"),
            message => { if (message == "PARTITION_DEPLOYED=esp") Environment.Exit(91); }, CancellationToken.None);
        throw new IOException("Crash boundary not reached.");
    }
    private static async Task CrashProcessAsync(string source, string directory, InstallationTargetKind kind)
    {
        var start = new ProcessStartInfo(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe"))
            { UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { typeof(App).Assembly.Location, "--cli", "native-partition-crash", source, directory, kind.ToString() })
            start.ArgumentList.Add(arg);
        using var process = Process.Start(start) ?? throw new IOException("Crash worker did not start.");
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(3));
        try { await process.WaitForExitAsync(timeout.Token); }
        catch { if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(); } throw; }
        if (process.ExitCode != 91) throw new IOException("Expected exact crash boundary exit 91, got " + process.ExitCode);
    }
    private static JsonObject Journal(string path) => JsonNode.Parse(File.ReadAllText(path))?.AsObject() ?? throw new IOException("Missing journal.");
    private static Guid TargetId(string state) => Guid.Parse(Journal(state)["target_id"]!.GetValue<string>());
    private static async Task ExpectRefusalAsync(Func<Task> action, string expected)
    {
        try { await action(); }
        catch (IOException error) when (error.Message.Contains(expected, StringComparison.Ordinal)) { return; }
        throw new IOException("Expected refusal: " + expected);
    }
    public static async Task<string> RecoverySessionAsync(string source, InstallationTargetKind kind)
    {
        using var image = new PreparedDiskImage(source);
        if (image.Layout.Size != InstallationController.Capacity) throw new IOException("Expected full prepared system.");
        MediaSpace.RequirePartitionStaging(Backend.Root, image.Layout.Size);
        var directory = DirectoryFor();
        await CrashProcessAsync(source, directory, kind);
        var id = Guid.NewGuid().ToString("N");
        var session = new InstallationSession(1, id, kind, source, true, "running", "writing", directory, null, DateTime.UtcNow);
        var folder = InstallationController.SessionDirectory(session); Directory.CreateDirectory(folder);
        var path = Path.Combine(folder, "session.json"); InstallationController.Save(path, session);
        return path;
    }
    public static async Task<string> RecoveryAsync(Action<string> log)
    {
        var source = await CompactImageAsync(); using var image = new PreparedDiskImage(source);
        var events = new List<string>(); var cases = new List<string>();
        foreach (var kind in new[] { InstallationTargetKind.InternalShared, InstallationTargetKind.ExternalDisk })
        {
            var directory = DirectoryFor(); cases.Add(directory);
            var state = Path.Combine(directory, "state.json"); var path = Path.Combine(directory, "media.vhd");
            await CrashProcessAsync(source, directory, kind);
            var initial = Journal(state);
            if (initial["status"]!.GetValue<string>() != "in_progress" || initial["completed"]!.AsArray().Count != 1)
                throw new IOException("Abrupt process exit did not leave an interrupted journal.");
            var id = TargetId(state); byte[] gpt;
            using (var reopened = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id))
            {
                gpt = Primary(reopened);
                // Simulate an unrecorded partial write in the next partition.
                var next = image.Layout.For(kind).Single(p => p.Name == "efi-A");
                using var locks = PartitionVolumeLocks.Acquire(reopened, [next]);
                using var raw = reopened.OpenDevice(); raw.Position = next.Offset;
                var incomplete = Enumerable.Repeat((byte)0xE7, 4096).ToArray(); raw.Write(incomplete); raw.Flush(true);
                await ExpectRefusalAsync(() => Task.Run(() => { using var second = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id); }), "file");
            }
            var messages = new List<string>();
            await PartitionDeployment.ResumeOwnedAsync(image, kind, state, text => { messages.Add(text); log(text); }, CancellationToken.None);
            if (!messages.Where(t => t.StartsWith("PARTITION_RECHECKED=")).SequenceEqual(["PARTITION_RECHECKED=esp"])
                || messages.Count(t => t.StartsWith("PARTITION_DEPLOYED=")) != 7) throw new IOException("Wrong resume prefix or write count.");
            using (var reopened = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id))
            {
                if (!gpt.AsSpan().SequenceEqual(Primary(reopened))) throw new IOException("Resume changed GPT.");
                using (var locks = PartitionVolumeLocks.Acquire(reopened, image.Layout.For(kind).Where(p => PreparedDisk.Roles.Contains(p.Name)).ToArray()))
                using (var raw = reopened.OpenDevice())
                    foreach (var part in image.Layout.System)
                        await PartitionDeployment.VerifyRangeAsync(image.Stream, raw, part, reopened.Size, _ => { }, CancellationToken.None);
                if (kind == InstallationTargetKind.InternalShared)
                {
                    var probe = await ProbeAsync(reopened);
                    var sentinel = probe.Volumes.Single(v => v.Number == 2).Path + "preserved.txt";
                    if (File.ReadAllText(sentinel) != "OXP partition sentinel 2\n") throw new IOException("Recovery changed Windows sentinel.");
                }
            }
            var result = Journal(state);
            if (result["status"]!.GetValue<string>() != "complete" || result["attempt"]!.GetValue<int>() != 2
                || result["completed"]!.AsArray().Count != 8 || result["boot_ready"]!.GetValue<bool>()) throw new IOException("Recovery completion state invalid.");
            if (Directory.GetFiles(directory, "state.json.before-resume-*.json").Length != 1) throw new IOException("Original journal not preserved.");
            events.Add(kind + ":abrupt-process-exit-reopen-prefix-recheck-partial-range-restart-eight-full-byte-comparisons-gpt-preserved");
            if (kind == InstallationTargetKind.InternalShared) events.Add("internal:Windows-NTFS-sentinel-preserved");
            messages.Clear();
            await PartitionDeployment.ResumeOwnedAsync(image, kind, state, messages.Add, CancellationToken.None);
            if (messages.Count != 16 || messages.Count(t => t.StartsWith("PARTITION_RECHECKED=")) != 8
                || messages.Any(t => !t.StartsWith("PARTITION_RECHECKED=") && !t.StartsWith("PARTITION_RECHECKING="))) throw new IOException("Complete retry rewrote content.");
            events.Add(kind + ":completed-retry-only-rechecks-no-content-writes");
            using (var stop = new CancellationTokenSource())
            {
                var cancelled = false; messages.Clear();
                try
                {
                    await PartitionDeployment.ResumeOwnedAsync(image, kind, state, text => { messages.Add(text); stop.Cancel(); }, stop.Token);
                }
                catch (OperationCanceledException) { cancelled = true; }
                if (!cancelled || !messages.SequenceEqual(["PARTITION_RECHECKING=esp"])
                    || Journal(state)["status"]!.GetValue<string>() != "cancelled"
                    || Journal(state)["completed"]!.AsArray().Count != 8)
                    throw new IOException("Recovery cancellation lost the completed prefix or continued.");
            }
            messages.Clear();
            await PartitionDeployment.ResumeOwnedAsync(image, kind, state, messages.Add, CancellationToken.None);
            if (Journal(state)["status"]!.GetValue<string>() != "complete" || messages.Count != 16
                || messages.Count(t => t.StartsWith("PARTITION_RECHECKED=")) != 8
                || messages.Any(t => !t.StartsWith("PARTITION_RECHECKED=") && !t.StartsWith("PARTITION_RECHECKING="))) throw new IOException("Cancelled recovery could not be retried without writing.");
            events.Add(kind + ":cancel-during-prefix-recheck-detach-and-retry-without-content-write");
        }
        // A damaged completed partition must prevent every subsequent content write.
        {
            var directory = DirectoryFor(); cases.Add(directory); var state = Path.Combine(directory, "state.json"); var path = Path.Combine(directory, "media.vhd");
            await CrashProcessAsync(source, directory, InstallationTargetKind.ExternalDisk); var id = TargetId(state);
            byte[] before;
            using (var disk = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id))
            using (var locks = PartitionVolumeLocks.Acquire(disk, image.Layout.For(InstallationTargetKind.ExternalDisk)))
            using (var raw = disk.OpenDevice())
            {
                raw.Position = image.Layout.System[0].Offset; raw.Write(new byte[512]); raw.Flush(true);
                before = new byte[4096]; raw.Position = image.Layout.System[1].Offset; raw.ReadExactly(before);
            }
            await ExpectRefusalAsync(() => PartitionDeployment.ResumeOwnedAsync(image, InstallationTargetKind.ExternalDisk, state, log, CancellationToken.None), "Previously completed partition differs");
            using (var disk = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id))
            using (var raw = disk.OpenDevice())
            {
                var after = new byte[before.Length]; raw.Position = image.Layout.System[1].Offset; raw.ReadExactly(after);
                if (!before.AsSpan().SequenceEqual(after)) throw new IOException("Damaged prefix allowed a subsequent write.");
            }
            events.Add("damaged-completed-partition-refused-before-next-partition-write");
            var valid = File.ReadAllText(state);
            foreach (var mutation in new[] { "source", "prefix", "kind", "old-schema", "target-id" })
            {
                var changed = JsonNode.Parse(valid)!.AsObject();
                switch (mutation)
                {
                    case "source": changed["source"]!["WriteTime"] = image.Identity.WriteTime + 1; break;
                    case "prefix": changed["completed"] = new JsonArray("efi-A"); break;
                    case "kind": changed["kind"] = InstallationTargetKind.InternalShared.ToString(); break;
                    case "old-schema": changed["schema"] = 1; break;
                    case "target-id": changed["target_id"] = Guid.NewGuid().ToString(); break;
                }
                File.WriteAllText(state, changed.ToJsonString()); var expected = File.ReadAllText(state);
                await ExpectRefusalAsync(() => PartitionDeployment.ResumeOwnedAsync(image, InstallationTargetKind.ExternalDisk, state, log, CancellationToken.None),
                    mutation == "old-schema" ? "predates" : mutation == "target-id" ? "receipt differs" : "Recovery journal");
                if (File.ReadAllText(state) != expected) throw new IOException("Rejected journal was overwritten.");
                events.Add(mutation + ":refused-journal-preserved");
            }
            File.WriteAllText(state, valid);
            // Preserve native VHD GUID but replace the ordinary backing file.
            var displaced = Path.Combine(directory, "original.vhd");
            File.Move(path, displaced); File.Copy(displaced, path);
            await ExpectRefusalAsync(() => Task.Run(() => { using var disk = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id); }), "file identity changed");
            events.Add("same-path-same-VHD-guid-replacement-refused-by-file-id");
            // Missing receipt is never silently reconstructed.
            File.Move(path + ".owner.json", path + ".owner.saved.json");
            await ExpectRefusalAsync(() => Task.Run(() => { using var disk = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, id); }), "ordinary existing file");
            events.Add("missing-ownership-record-refused");
        }
        var proof = Path.Combine(Path.GetDirectoryName(source)!, "recovery-checks.json");
        await File.WriteAllTextAsync(proof, JsonSerializer.Serialize(new { passed = true, source, cases, events,
            scope = "Windows owned VHD process-exit and partition recovery; no actual power loss, host firmware or physical drive acceptance" }));
        return proof;
    }
}
