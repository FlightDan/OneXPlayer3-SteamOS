using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public static class MediaWriterChecks
{
    public static string NativeVhdSmoke()
    {
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "windows-media-smoke-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "media.vhd");
        string device; Guid id;
        using (var disk = new VirtualMediaDisk(path, 16 * 1024 * 1024))
        {
            device = disk.PhysicalPath; id = disk.Id;
            using var stream = disk.OpenDevice();
            var expected = Enumerable.Range(0, 4096).Select(i => (byte)(i % 251)).ToArray();
            stream.Position = 0; stream.Write(expected); stream.Flush(true);
            stream.Position = 0; var actual = new byte[expected.Length]; stream.ReadExactly(actual);
            if (!actual.AsSpan().SequenceEqual(expected)) throw new IOException("Native VHD byte readback differs.");
        }
        File.WriteAllText(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new
        { passed = true, path, id, device, scope = "New 16MiB work-directory VHD, Windows attach without drive letters, physical path bound from owned VHD handle, native capacity/512-sector/file-backed bus checks, raw 4KiB write/readback and detach. No USB or existing disk writes." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
    public static async Task<string> FullWriteAsync(string image, bool cancel)
    {
        using var cancellation = new CancellationTokenSource();
        var operation = await MediaWriterController.RunVirtualAsync(image, progress =>
        {
            if (cancel && progress.Stage == "writing" && progress.Written >= 64 * 1024 * 1024) cancellation.Cancel();
        }, cancellation.Token);
        var result = operation.Result;
        if (cancel)
        {
            if (result.Status != "cancelled" || result.Written <= 0 || result.Written >= result.Total || result.Verified != 0 || !result.Detached)
                throw new IOException("Helper cancellation did not stop a partial unverified copy and detach.");
        }
        else if (result.Status != "complete" || result.Written != result.Total || result.Verified != result.Total || !result.Detached)
            throw new IOException("Administrator helper did not complete native copy/readback/detach: " + result.Error);
        File.WriteAllText(Path.Combine(operation.Directory, "check-result.json"), JsonSerializer.Serialize(new
        { passed = true, cancel, helper = "result.json", scope = cancel
            ? "Separate administrator process signalled during real Windows VHD raw image copy; partial unverified result persisted and VHD detached. No physical USB execution."
            : "Separate administrator process, source-handle identity reread, fresh owned Windows VHD attachment, native aligned whole-image write, ordinary full byte readback and detach. No physical USB or boot acceptance." }, new JsonSerializerOptions { WriteIndented = true }));
        return operation.Directory;
    }
    public static async Task<string> ChangedSourceAsync()
    {
        var image = Path.Combine(Backend.Root, "output", "media-source-negative-" + Guid.NewGuid().ToString("N") + ".img");
        Directory.CreateDirectory(Path.GetDirectoryName(image)!);
        using (var file = new FileStream(image, FileMode.CreateNew, FileAccess.Write))
        {
            file.SetLength(32 * 1024 * 1024); var header = new byte[1024]; header[510] = 0x55; header[511] = 0xAA;
            System.Text.Encoding.ASCII.GetBytes("EFI PART").CopyTo(header, 512);
            BitConverter.GetBytes(92u).CopyTo(header, 524); BitConverter.GetBytes(1ul).CopyTo(header, 536);
            BitConverter.GetBytes(65535ul).CopyTo(header, 544); Guid.NewGuid().ToByteArray().CopyTo(header, 568);
            file.Write(header); file.Flush(true);
        }
        var operation = await MediaWriterController.RunVirtualAsync(image, _ => { }, CancellationToken.None, _ =>
        {
            // Change the actual reviewed file before the child opens it.
            using (var file = new FileStream(image, FileMode.Open, FileAccess.Write, FileShare.None))
            { file.Position = 5000; file.WriteByte(1); file.Flush(true); }
            File.SetLastWriteTimeUtc(image, DateTime.UtcNow.AddSeconds(2));
        });
        if (operation.Result.Status != "failed" || operation.Result.Written != 0 || File.Exists(Path.Combine(operation.Directory, "media.vhd"))
            || operation.Result.Error?.Contains("changed after review", StringComparison.Ordinal) != true)
            throw new IOException("Changed source did not fail before target creation.");
        File.WriteAllText(Path.Combine(operation.Directory, "check-result.json"), JsonSerializer.Serialize(new
        { passed = true, scope = "Actual reviewed source file changed before child execution; independent admin helper rejected identity/time mismatch before VHD creation and before any raw writes. Synthetic source is not a bootable image." }));
        return operation.Directory;
    }
    public static async Task<string> HelperGuardsAsync(string image)
    {
        var source = MediaSource.Read(image); var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "media-guards-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory); var cases = new List<object>();
        foreach (var variant in new[] { "physical-kind", "missing-confirmation", "insufficient-capacity" })
        {
            var nonce = Guid.NewGuid().ToString("N"); var folder = Path.Combine(InstallerWorkspace.DirectoryPath, "media-" + nonce); Directory.CreateDirectory(folder);
            var job = new MediaJob(1, variant == "physical-kind" ? "usb-image-write" : "virtual-media-validation", nonce, source,
                variant == "insufficient-capacity" ? source.Length - 512 : source.Length,
                variant == "missing-confirmation" ? "" : "erase-new-virtual-medium");
            var path = Path.Combine(folder, "media-job.json"); File.WriteAllText(path, JsonSerializer.Serialize(job));
            var start = new System.Diagnostics.ProcessStartInfo(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe"))
            { UseShellExecute = false, CreateNoWindow = true };
            start.ArgumentList.Add(Path.Combine(Backend.Root, "app/bin/Debug/net10.0-windows/OxpInstaller.dll")); start.ArgumentList.Add("--media-helper"); start.ArgumentList.Add(path);
            using var child = System.Diagnostics.Process.Start(start) ?? throw new IOException("Guard helper did not start.");
            await child.WaitForExitAsync();
            if (child.ExitCode == 0 || File.Exists(Path.Combine(folder, "media.vhd"))) throw new IOException("Unaccepted media job created a target: " + variant);
            cases.Add(new { variant, exit = child.ExitCode, folder, target_created = false });
        }
        File.WriteAllText(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new
        { passed = true, cases, scope = "Real separate helper processes rejected physical kind, missing confirmation and insufficient capacity before target creation. No physical device path supplied or opened." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
}
