using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public static class MediaFaultChecks
{
    public static async Task<string> RunAsync(string image)
    {
        var identity = MediaSource.Read(image);
        if (identity.Length < 256L * 1024 * 1024) throw new IOException("Helper callback failure validation requires at least 256MiB source.");
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "media-faults-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var cases = new List<object>(); const long length = 16 * 1024 * 1024;
        foreach (var mode in new[] { "capacity", "readback-mismatch", "verify-cancel", "closed-handle" })
        {
            var path = Path.Combine(directory, mode + ".vhd"); MediaProgress? last = null; Exception? failure = null; var cancel = false;
            using (var disk = new VirtualMediaDisk(path, length))
            using (var target = disk.OpenDevice())
            using (var source = MediaSource.Open(image))
            {
                var sentinel = Enumerable.Range(0, 4096).Select(i => (byte)(i % 251)).ToArray(); target.Write(sentinel); target.Flush(true);
                try
                {
                    await AlignedMediaCopy.CopyAndVerifyAsync(source, target, mode == "capacity" ? length + 512 : length, disk.Size, progress =>
                    {
                        last = progress;
                        if (mode == "closed-handle" && progress.Stage == "writing" && progress.Written == 4 * 1024 * 1024) target.Dispose();
                        if (mode == "verify-cancel" && progress.Stage == "verifying") cancel = true;
                        if (mode == "readback-mismatch" && progress.Stage == "writing" && progress.Written == length)
                        {
                            target.Position = 4096; var sector = new byte[512]; target.ReadExactly(sector); sector[0] ^= 1; target.Position = 4096; target.Write(sector); target.Flush(true);
                        }
                    }, () => cancel);
                }
                catch (Exception error) { failure = error; }
                if (mode == "capacity")
                {
                    if (failure is not IOException || last != null) throw new IOException("Insufficient device capacity did not refuse before writes.");
                    target.Position = 0; var actual = new byte[sentinel.Length]; target.ReadExactly(actual);
                    if (!actual.AsSpan().SequenceEqual(sentinel)) throw new IOException("Capacity refusal changed owned target bytes.");
                }
                else if (mode == "readback-mismatch" && (failure is not IOException || !failure.Message.StartsWith("Media byte readback differs", StringComparison.Ordinal) || last?.Written != length || last.Verified != 0))
                    throw new IOException("Actual owned target mismatch was not rejected.");
                else if (mode == "verify-cancel" && (failure is not OperationCanceledException || last?.Written != length || last.Verified <= 0 || last.Verified >= length))
                    throw new IOException("Readback cancellation did not preserve incomplete verification.");
                else if (mode == "closed-handle" && (failure is not AggregateException combined || combined.InnerExceptions.Count != 2 || combined.InnerExceptions.Any(e => e is not ObjectDisposedException) || last?.Written != 4 * 1024 * 1024))
                    throw new IOException("Closed native write handle and failed final flush were not both preserved.");
            }
            cases.Add(new { mode, path, passed = true, progress = last, error = failure?.ToString(), scope = "New 16MiB Windows VHD; real raw bytes/handles, no physical media." });
        }
        using (var cancellation = new CancellationTokenSource())
        {
            var operation = await MediaWriterController.RunVirtualAsync(image, _ => { }, cancellation.Token, _ => cancellation.Cancel());
            if (operation.Result.Status != "cancelled" || operation.Result.Written != 0 || operation.Result.Verified != 0 || !operation.Result.Detached || operation.Result.Vhd != null)
                throw new IOException("Cancellation after review but before child target creation was not safe.");
            cases.Add(new { mode = "helper-pre-create-cancel", operation.Directory, operation.Result, passed = true });
        }
        string? callbackDirectory = null; var callbackFailed = false;
        try
        {
            await MediaWriterController.RunVirtualAsync(image, progress =>
            {
                if (progress.Stage == "writing" && progress.Written >= 4 * 1024 * 1024) throw new InvalidOperationException("Deliberate parent progress callback failure.");
            }, CancellationToken.None, path => callbackDirectory = path);
        }
        catch (InvalidOperationException error) when (error.Message == "Deliberate parent progress callback failure.") { callbackFailed = true; }
        if (!callbackFailed || callbackDirectory == null) throw new IOException("Parent callback failure did not propagate.");
        var result = JsonSerializer.Deserialize<MediaResult>(File.ReadAllText(Path.Combine(callbackDirectory, "result.json"))) ?? throw new IOException("Child result absent after callback failure cleanup.");
        if (result.Status != "cancelled" || result.Written <= 0 || result.Written >= result.Total || result.Verified != 0 || !result.Detached) throw new IOException("Parent failure did not wait for child's partial-copy cleanup.");
        cases.Add(new { mode = "parent-callback-failure-cleanup", directory = callbackDirectory, result, passed = true });
        var spaceDirectory = Path.Combine(InstallerWorkspace.DirectoryPath, "volume-lock-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(spaceDirectory);
        var spacePath = Path.Combine(spaceDirectory, "media.vhd"); MediaSpaceInfo space;
        using (var disk = new VirtualMediaDisk(spacePath, 128 * 1024 * 1024))
        {
            var json = await Backend.PowerShellAsync("vhd-test-volumes.ps1", ["-VhdPath", spacePath, "-Prepare"], _ => { }, CancellationToken.None);
            using var snapshot = JsonDocument.Parse(json); var volume = snapshot.RootElement.GetProperty("Paths")[0].GetString() ?? throw new IOException("Owned space volume missing.");
            if (snapshot.RootElement.GetProperty("DiskNumber").GetInt32() != disk.BoundDiskNumber()) throw new IOException("Wrong work-space test disk.");
            space = MediaSpace.Query(volume, disk.Size); var refused = false;
            try { MediaSpace.Require(volume, disk.Size); } catch (IOException error) when (error.Message.StartsWith("Insufficient work-volume space", StringComparison.Ordinal)) { refused = true; }
            if (!refused || space.Available >= space.Required) throw new IOException("Actual small work volume was not refused by available-space preflight.");
        }
        cases.Add(new { mode = "actual-owned-volume-space-refusal", path = spacePath, space, passed = true, scope = "Windows native available-space query on new small NTFS VHD; no child VHD creation, no host volume filled." });
        File.WriteAllText(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new { passed = true, cases,
            scope = "Real owned VHD capacity refusal, changed readback bytes, verification cancellation and closed raw handle/flush failure; real separate helper pre-create cancellation and parent exception cleanup; native small work-volume space refusal. No physical USB, unplug, injected disk-full I/O or normal-user UAC acceptance." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
}