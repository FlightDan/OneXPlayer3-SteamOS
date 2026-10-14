using System.Buffers.Binary;
using System.ComponentModel;
using System.IO;
using System.Text.Json;

namespace OxpInstaller;

public static partial class PartitionDeploymentChecks
{
    private const long MiB = 1024 * 1024;
    private sealed record Volume(int Number, string Path, string FileSystem);
    private sealed record Probe(int Number, long Size, Volume[] Volumes);
    private static string DirectoryFor()
    {
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "partition-deploy-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory); return directory;
    }
    private static async Task<Probe> ProbeAsync(VirtualMediaDisk disk, string action = "probe")
    {
        var json = await Backend.PowerShellAsync("partition-vhd-lab.ps1", ["-VhdPath", disk.PathOnHost, "-Action", action], _ => { }, CancellationToken.None);
        var result = JsonSerializer.Deserialize<Probe>(json) ?? throw new IOException("Owned partition probe missing.");
        if (result.Number != disk.BoundDiskNumber() || result.Size != disk.Size) throw new IOException("Owned partition probe binding differs.");
        return result;
    }
    private static PreparedDisk CompactPlan()
    {
        var basic = Guid.Parse("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7");
        var esp = Guid.Parse("c12a7328-f81f-11d2-ba4b-00a0c93ec93b");
        var types = new[] { esp, basic, basic, Guid.Parse("4f68bce3-e8cd-4db1-96e7-fbcaf984b709"),
            Guid.Parse("4f68bce3-e8cd-4db1-96e7-fbcaf984b709"), Guid.Parse("4d21b016-b534-45c2-a9fb-5c16e091fd2d"),
            Guid.Parse("4d21b016-b534-45c2-a9fb-5c16e091fd2d"), Guid.Parse("933ac7e1-2eb4-4f13-b844-0e14e2aef915") };
        var parts = new List<PreparedPartition> {
            new(1, "Windows EFI fixture", esp, Guid.NewGuid(), MiB, 64 * MiB, 0),
            new(2, "Windows data fixture", basic, Guid.NewGuid(), 65 * MiB, 64 * MiB, 0x8000000000000000)
        };
        var cursor = 160 * MiB; var sizes = new long[] { 64, 64, 64, 16, 16, 8, 8, 16 };
        for (var i = 0; i < sizes.Length; i++)
        {
            parts.Add(new(i + 3, PreparedDisk.Roles[i], types[i], Guid.NewGuid(), cursor, sizes[i] * MiB, 0));
            cursor += sizes[i] * MiB;
        }
        return new(Guid.NewGuid(), 512 * MiB, parts.ToArray());
    }
    private static async Task<string> CompactImageAsync()
    {
        var directory = DirectoryFor(); var plan = CompactPlan(); var image = Path.Combine(directory, "prepared.img");
        using (var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), plan.Size))
        {
            OwnedPartitionLayout.Initialize(disk, plan, plan.Partitions);
            await ProbeAsync(disk, "format-protected");
            using (var locks = PartitionVolumeLocks.Acquire(disk, plan.System))
            using (var raw = disk.OpenDevice())
            {
                var buffer = new byte[4 * 1024 * 1024];
                foreach (var p in plan.System)
                {
                    Array.Fill(buffer, (byte)(p.Number * 17)); raw.Position = p.Offset;
                    for (long n = 0; n < p.Size; n += buffer.Length) await raw.WriteAsync(buffer.AsMemory(0, (int)Math.Min(buffer.Length, p.Size - n)));
                }
                raw.Flush(true);
            }
            using (var locks = PartitionVolumeLocks.Acquire(disk, plan.Partitions))
            using (var raw = disk.OpenDevice())
            using (var output = new FileStream(image, FileMode.CreateNew, FileAccess.Write))
            {
                var buffer = new byte[4 * 1024 * 1024]; raw.Position = 0;
                for (long n = 0; n < disk.Size; n += buffer.Length)
                {
                    var count = (int)Math.Min(buffer.Length, disk.Size - n); await raw.ReadExactlyAsync(buffer.AsMemory(0, count)); await output.WriteAsync(buffer.AsMemory(0, count));
                }
                output.Flush(true);
            }
        }
        return image;
    }
    private static async Task<PartitionVolumeLocks> SeedProtectedAsync(PreparedDiskImage image, VirtualMediaDisk disk, CancellationToken token = default)
    {
        var locks = PartitionVolumeLocks.Acquire(disk, image.Layout.Protected);
        try
        {
            using var target = disk.OpenDevice();
            foreach (var p in image.Layout.Protected)
                await PartitionDeployment.CopyRangeAsync(image.Stream, target, p.Offset, p.Offset, p.Size, disk.Size, _ => { }, token);
            return locks;
        }
        catch { locks.Dispose(); throw; }
    }
    private static async Task CompareProtectedAsync(PreparedDiskImage image, VirtualMediaDisk disk, bool alreadyLocked = false)
    {
        using var locks = alreadyLocked ? null : PartitionVolumeLocks.Acquire(disk, image.Layout.Protected);
        using var target = disk.OpenDevice(); var first = new byte[4 * 1024 * 1024]; var second = new byte[first.Length];
        foreach (var p in image.Layout.Protected)
        {
            image.Stream.Position = target.Position = p.Offset;
            for (long n = 0; n < p.Size; n += first.Length)
            {
                var count = (int)Math.Min(first.Length, p.Size - n);
                await image.Stream.ReadExactlyAsync(first.AsMemory(0, count)); await target.ReadExactlyAsync(second.AsMemory(0, count));
                if (!first.AsSpan(0, count).SequenceEqual(second.AsSpan(0, count))) throw new IOException("Protected partition bytes differ: " + p.Name + " at block " + n);
            }
        }
    }
    private static byte[] Primary(VirtualMediaDisk disk)
    {
        using var target = disk.OpenDevice(); var bytes = new byte[34 * 512]; target.Position = 0; target.ReadExactly(bytes); return bytes;
    }
    public static async Task<string> RunAsync(Action<string> log)
    {
        var imagePath = await CompactImageAsync(); var events = new List<string>(); var operations = new List<string>();
        using var image = new PreparedDiskImage(imagePath);
        events.Add("native-windows-gpt-source-primary-backup-and-role-metadata");
        foreach (var kind in new[] { InstallationTargetKind.InternalShared, InstallationTargetKind.ExternalDisk })
        {
            var directory = DirectoryFor(); operations.Add(directory);
            using (var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size))
            {
                OwnedPartitionLayout.Initialize(disk, image.Layout, kind == InstallationTargetKind.InternalShared ? image.Layout.Protected : []);
                FileStream? held = null; string? preserved = null;
                if (kind == InstallationTargetKind.InternalShared)
                {
                    using (await SeedProtectedAsync(image, disk)) { } OwnedPartitionLayout.Refresh(disk);
                    var probe = await ProbeAsync(disk); preserved = probe.Volumes.Single(v => v.Number == 2).Path + "preserved.txt";
                    if (File.ReadAllText(preserved) != "OXP partition sentinel 2\n") throw new IOException("Seeded NTFS sentinel differs.");
                    held = new FileStream(preserved, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                    PartitionDeployment.RequireSourceOutsideTargets(held, disk.BoundDiskNumber(), image.Layout.System);
                    var refused = false;
                    try { PartitionDeployment.RequireSourceOutsideTargets(held, disk.BoundDiskNumber(), image.Layout.Protected); }
                    catch (IOException) { refused = true; }
                    if (!refused) throw new IOException("A same-disk source overlap was accepted.");
                    events.Add("actual-same-disk-protected-source-allowed-target-source-overlap-refused");
                }
                try { await PartitionDeployment.ApplyOwnedAsync(image, disk, kind, Path.Combine(directory, "state.json"), log, CancellationToken.None); }
                finally { held?.Dispose(); }
                if (preserved != null)
                {
                    if (File.ReadAllText(preserved) != "OXP partition sentinel 2\n") throw new IOException("Protected open NTFS file was lost.");
                    events.Add("internal-eight-range-write-readback-protected-open-ntfs-file-preserved");
                }
                else events.Add("external-only-eight-system-partitions-guid-retention-full-range-readback");
                using var state = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "state.json")));
                if (state.RootElement.GetProperty("status").GetString() != "complete" || state.RootElement.GetProperty("completed").GetArrayLength() != 8
                    || state.RootElement.GetProperty("boot_ready").GetBoolean()) throw new IOException("Deployment state falsely reports boot readiness.");
            }
            events.Add(kind + "-owned-vhd-detached");
        }
        // Freeze existing filesystems before copying so mount-generated NTFS
        // journals cannot be confused with an out-of-range installer write.
        {
            var directory = DirectoryFor(); operations.Add(directory);
            using var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size);
            OwnedPartitionLayout.Initialize(disk, image.Layout, image.Layout.Protected);
            using var frozen = await SeedProtectedAsync(image, disk);
            await PartitionDeployment.ApplyOwnedAsync(image, disk, InstallationTargetKind.InternalShared,
                Path.Combine(directory, "state.json"), log, CancellationToken.None);
            await CompareProtectedAsync(image, disk, true);
            events.Add("frozen-protected-fat-ntfs-whole-partition-byte-equality-after-complete-system-deployment");
        }
        // A real busy target file must refuse locks before any explicit dismount;
        // protected NTFS files remain usable while target locks are acquired.
        {
            var directory = DirectoryFor(); operations.Add(directory);
            using var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size);
            OwnedPartitionLayout.Initialize(disk, image.Layout, image.Layout.Protected); using (await SeedProtectedAsync(image, disk)) { }
            OwnedPartitionLayout.Append(disk, image.Layout, InstallationTargetKind.InternalShared);
            var probe = await ProbeAsync(disk, "format-lock");
            var busy = probe.Volumes.Single(v => v.Number == 4).Path + "preserved.txt";
            using (var file = new FileStream(busy, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            {
                var refused = false;
                try { using var unexpected = PartitionVolumeLocks.Acquire(disk, image.Layout.System); }
                catch (Win32Exception) { refused = true; }
                if (!refused || File.ReadAllText(busy) != "OXP partition sentinel 4\n") throw new IOException("Busy target was not refused without changing its file.");
            }
            using (var locks = PartitionVolumeLocks.Acquire(disk, image.Layout.System))
                if (locks.Count < 2) throw new IOException("Actual target GUID volumes were not locked.");
            if (File.ReadAllText(busy) != "OXP partition sentinel 4\n") throw new IOException("Target locks were not released.");
            events.Add("busy-target-refused-all-earlier-locks-released-real-ntfs-preserved");
        }
        // Cancellation after one completely verified role cannot mark the disk complete.
        {
            var directory = DirectoryFor(); operations.Add(directory);
            using var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size);
            OwnedPartitionLayout.Initialize(disk, image.Layout, image.Layout.Protected);
            using var frozen = await SeedProtectedAsync(image, disk);
            using var cancel = new CancellationTokenSource(); var observed = false;
            try { await PartitionDeployment.ApplyOwnedAsync(image, disk, InstallationTargetKind.InternalShared, Path.Combine(directory, "state.json"),
                message => { log(message); if (message == "PARTITION_DEPLOYED=esp") cancel.Cancel(); }, cancel.Token); }
            catch (OperationCanceledException) { observed = true; }
            using var state = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "state.json")));
            if (!observed || state.RootElement.GetProperty("status").GetString() != "cancelled"
                || state.RootElement.GetProperty("completed").GetArrayLength() != 1 || state.RootElement.GetProperty("boot_ready").GetBoolean())
                throw new IOException("Cancelled partial deployment was marked complete.");
            await CompareProtectedAsync(image, disk, true); events.Add("cancel-after-first-verified-role-persisted-incomplete-protected-bytes-preserved");
        }
        // A native range mismatch must be rejected before partition creation or data writes.
        {
            var directory = DirectoryFor(); operations.Add(directory);
            using var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size);
            var different = image.Layout.Protected.Select((p, i) => i == 1 ? p with { Size = p.Size - 512 } : p).ToArray();
            OwnedPartitionLayout.Initialize(disk, image.Layout, different); var before = Primary(disk); var refused = false;
            try { await PartitionDeployment.ApplyOwnedAsync(image, disk, InstallationTargetKind.InternalShared, Path.Combine(directory, "state.json"), log, CancellationToken.None); }
            catch (IOException) { refused = true; }
            if (!refused || !before.AsSpan().SequenceEqual(Primary(disk))) throw new IOException("Native changed-range refusal altered GPT.");
            events.Add("native-target-range-mismatch-refused-before-gpt-or-partition-write");
            using var raw = disk.OpenDevice(); before = Primary(disk); refused = false;
            try { await PartitionDeployment.CopyRangeAsync(image.Stream, raw, 0, 0, 512, disk.Size, _ => { }, CancellationToken.None); }
            catch (IOException) { refused = true; }
            if (!refused || !before.AsSpan().SequenceEqual(Primary(disk))) throw new IOException("Partition copy accepted a GPT-sector target.");
            events.Add("gpt-sector-target-refused-with-native-metadata-unchanged");
        }
        // Reject inconsistent prepared metadata before a target is created.
        {
            var directory = DirectoryFor(); var broken = Path.Combine(directory, "prepared.img");
            using (var output = new FileStream(broken, FileMode.CreateNew, FileAccess.ReadWrite))
            {
                output.SetLength(image.Layout.Size);
                var bytes = new byte[34 * 512]; image.Stream.Position = 0; image.Stream.ReadExactly(bytes); output.Write(bytes);
                bytes = new byte[33 * 512]; image.Stream.Position = image.Layout.Size - bytes.Length; image.Stream.ReadExactly(bytes);
                output.Position = image.Layout.Size - bytes.Length; output.Write(bytes);
                output.Position = 1024 + 16; var previous = output.ReadByte(); output.Position--; output.WriteByte((byte)(previous ^ 0xff)); output.Flush(true);
            }
            var refused = false;
            try { using var unexpected = new PreparedDiskImage(broken); }
            catch (IOException) { refused = true; }
            if (!refused) throw new IOException("A primary/backup metadata mismatch was accepted.");
            events.Add("prepared-primary-backup-entry-mismatch-refused-before-target-creation");
        }
        // Unknown target kinds and a completed operation cannot authorize another write.
        {
            var directory = DirectoryFor(); operations.Add(directory);
            using var disk = new VirtualMediaDisk(Path.Combine(directory, "media.vhd"), image.Layout.Size);
            OwnedPartitionLayout.Initialize(disk, image.Layout, image.Layout.Protected);
            var before = Primary(disk); var refused = false; var statePath = Path.Combine(directory, "state.json");
            try { await PartitionDeployment.ApplyOwnedAsync(image, disk, (InstallationTargetKind)999, statePath, log, CancellationToken.None); }
            catch (IOException) { refused = true; }
            if (!refused || File.Exists(statePath) || !before.AsSpan().SequenceEqual(Primary(disk)))
                throw new IOException("Unknown target kind created state or changed GPT.");
            events.Add("unknown-target-kind-refused-before-state-or-disk-changes");
            File.WriteAllText(statePath, "existing operation must survive\n"); refused = false;
            try { await PartitionDeployment.ApplyOwnedAsync(image, disk, InstallationTargetKind.InternalShared, statePath, log, CancellationToken.None); }
            catch (IOException) { refused = true; }
            if (!refused || File.ReadAllText(statePath) != "existing operation must survive\n" || !before.AsSpan().SequenceEqual(Primary(disk)))
                throw new IOException("Existing deployment state was silently replaced.");
            events.Add("existing-operation-state-refused-with-journal-and-gpt-unchanged");
        }
        var report = Path.Combine(Path.GetDirectoryName(imagePath)!, "checks.json");
        File.WriteAllText(report, JsonSerializer.Serialize(new { passed = true, imagePath, operations, events,
            scope = "Actual native Windows newly owned VHDs; GPT creation/append, selected-volume locks, bounded partition copies and ordinary full byte readback. Compact role payloads are synthetic, not a SteamOS or physical boot proof." }, new JsonSerializerOptions { WriteIndented = true }));
        return report;
    }
    public static async Task<string> FullAsync(string fixture, InstallationTargetKind kind, Action<string> log, CancellationToken token)
    {
        Backend.VerifyFixture(fixture); var directory = DirectoryFor(); var imagePath = Path.Combine(directory, "prepared.img");
        MediaSpace.RequirePartitionStaging(directory, 80L * 1024 * 1024 * 1024);
        log("Exporting immutable QEMU deployment to an ordinary staging image.");
        await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe"),
            ["convert", "-O", "raw", QcowReadOnlyGraph.Filename(fixture), imagePath], log, token);
        return await PreparedAsync(imagePath, kind, log, token);
    }
    public static async Task<string> PreparedAsync(string imagePath, InstallationTargetKind kind, Action<string> log, CancellationToken token)
    {
        var directory = DirectoryFor();
        await WritePreparedAsync(imagePath, kind, directory, log, token);
        await ProveBootAsync(directory, kind, log, token);
        return directory;
    }
    public static async Task WritePreparedAsync(string imagePath, InstallationTargetKind kind, string directory, Action<string> log, CancellationToken token)
    {
        if (!Enum.IsDefined(kind)) throw new IOException("Unknown installation kind.");
        directory = Path.GetFullPath(directory);
        if (!System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(directory), "^partition-deploy-[0-9a-f]{32}$")) throw new IOException("Invalid owned deployment directory.");
        var path = Path.Combine(directory, "media.vhd");
        MediaSource.Ordinary(path, InstallerWorkspace.DirectoryPath, false);
        token.ThrowIfCancellationRequested();
        using var image = new PreparedDiskImage(imagePath);
        if (image.Layout.Size != 80L * 1024 * 1024 * 1024) throw new IOException("Full native deployment validation requires an 80GiB prepared fixture.");
        MediaSpace.RequirePartitionStaging(directory, image.Layout.Size);
        using (var disk = new VirtualMediaDisk(path, image.Layout.Size))
        {
            OwnedPartitionLayout.Initialize(disk, image.Layout, kind == InstallationTargetKind.InternalShared ? image.Layout.Protected : []);
            log("PARTITION_PHASE=preserving");
            using var frozen = kind == InstallationTargetKind.InternalShared ? await SeedProtectedAsync(image, disk, token) : null;
            await PartitionDeployment.ApplyOwnedAsync(image, disk, kind, Path.Combine(directory, "state.json"), log, token);
            if (kind == InstallationTargetKind.InternalShared) await CompareProtectedAsync(image, disk, true);
        }
        File.WriteAllText(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new { passed = true, kind = kind.ToString(), path, imagePath,
            detached = true, scope = "Real prepared SteamOS partition contents written/read back through native Windows owned VHD; host UEFI and hardware remain unaccepted" }));
    }
    public static async Task<string> ProveBootAsync(string directory, InstallationTargetKind kind, Action<string> log, CancellationToken token, bool refindManual = false)
    {
        var path = Path.Combine(directory, "media.vhd");
        var boot = await VirtualBoot.PartitionVhdAsync(path, log, token, refindManual);
        File.WriteAllText(Path.Combine(directory, "boot-proof.json"), JsonSerializer.Serialize(new { passed = true, boot, kind = kind.ToString(), path,
            scope = "Independent UEFI VM boot of the Windows partition-deployed VHD; no boot/install environment was run on the target first. No physical boot or Windows OS proof." }, new JsonSerializerOptions { WriteIndented = true }));
        return boot;
    }
}

