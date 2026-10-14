using System.Diagnostics;
using System.IO;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;
namespace OxpInstaller;
public sealed record UsbReviewJob(int Schema, string Kind, string Nonce, MediaSource Source, UsbDisk Reviewed);
public sealed record UsbReviewResult(string Status, NativeDiskInfo? Device, NativeLayout? Layout, NativeVolume? SourceVolume, NativeVolume[]? TargetVolumes, string? Error, string Scope);
public sealed record UsbReviewOperation(string Directory, UsbReviewResult Result);
public static class UsbNativeReview
{
    public static async Task<int> ExecuteAsync(string jobPath)
    {
        jobPath = Path.GetFullPath(jobPath); MediaSource.Ordinary(jobPath, InstallerWorkspace.DirectoryPath);
        if (Path.GetFileName(jobPath) != "usb-review-job.json" || new FileInfo(jobPath).Length > 65536) throw new IOException("Invalid read-only USB job path/size.");
        using var jobFile = new FileStream(jobPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        var job = await JsonSerializer.DeserializeAsync<UsbReviewJob>(jobFile, new JsonSerializerOptions { RespectRequiredConstructorParameters = true }) ?? throw new IOException("Empty read-only USB job.");
        if (job.Schema != 1 || job.Kind != "usb-native-readonly-review" || !Regex.IsMatch(job.Nonce, "^[0-9a-f]{32}$")
            || Path.GetFileName(Path.GetDirectoryName(jobPath)!) != "usb-review-" + job.Nonce || job.Source == null || job.Reviewed == null) throw new IOException("Invalid read-only USB review request.");
        NativeDiskInfo? device = null; NativeLayout? layout = null; NativeVolume? sourceVolume = null; NativeVolume[]? volumes = null; string? error = null;
        try
        {
            if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) throw new IOException("Administrator metadata review required.");
            using var source = MediaSource.Open(job.Source.Path);
            if (MediaSource.FromHandle(job.Source.Path, source) != job.Source) throw new IOException("Source image changed after review.");
            var fresh = await UsbMediaPlanning.ReadAsync(job.Source.Path, CancellationToken.None);
            var chosen = UsbMediaPlanning.Rebind(job.Reviewed, fresh, job.Source.Length);
            using var handle = NativeMediaDevice.OpenReviewedUsbReadOnly(chosen);
            device = NativeMediaDevice.Read(handle); layout = NativeMediaDevice.ReadLayout(handle, device.Size);
            sourceVolume = NativeVolumes.RequireDifferentSource(source, device.Number);
            if (sourceVolume.Extents[0].DiskNumber != fresh.SourceDiskNumber) throw new IOException("Native source handle and Windows source-disk mapping differ.");
            volumes = NativeVolumes.FindForDisk(device.Number, device.Size);
            foreach (var volume in volumes)
                if (!layout.Partitions.Any(p => p.Offset == volume.Extents[0].Offset && p.Size == volume.Extents[0].Size)) throw new IOException("Native target volume is not an exact reviewed partition range.");
            var again = await UsbMediaPlanning.ReadAsync(job.Source.Path, CancellationToken.None);
            var rebound = UsbMediaPlanning.Rebind(job.Reviewed, again, job.Source.Length);
            if (rebound.Number != device.Number || again.SourceDiskNumber != fresh.SourceDiskNumber) throw new IOException("Device/source mapping changed while holding the read-only handle.");
            var current = NativeMediaDevice.Read(handle); NativeMediaDevice.MatchUsb(rebound, current);
            if (current != device || !NativeMediaDevice.SameLayout(layout, NativeMediaDevice.ReadLayout(handle, device.Size))) throw new IOException("Native device/layout changed during review.");
            NativeVolumes.RequireComplete(device.Number, device.Size, volumes.Select(v => v.Path).ToArray());
            NativeVolumes.RequireDifferentSource(source, device.Number);
        }
        catch (Exception failure) { error = failure.ToString(); }
        var result = new UsbReviewResult(error == null ? "checked-readonly" : "refused", device, layout, sourceVolume, volumes, error,
            "Read-only native disk/volume metadata handles; fresh Windows identity and partition rebind, native bus/serial/device number/capacity/sector/layout, source-handle volume extents and complete target volume discovery. No lock, dismount, raw write, refresh or eject; physical write remains disabled.");
        var resultPath = Path.Combine(Path.GetDirectoryName(jobPath)!, "result.json"); MediaSource.Ordinary(resultPath, InstallerWorkspace.DirectoryPath, false);
        using var output = new FileStream(resultPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        await JsonSerializer.SerializeAsync(output, result); output.Flush(true);
        return error == null ? 0 : 1;
    }
    public static async Task<UsbReviewOperation> RunAsync(string image, UsbDisk reviewed, CancellationToken token)
    {
        token.ThrowIfCancellationRequested(); var source = MediaSource.Read(image); var nonce = Guid.NewGuid().ToString("N");
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "usb-review-" + nonce); Directory.CreateDirectory(directory);
        var jobPath = Path.Combine(directory, "usb-review-job.json"); await File.WriteAllTextAsync(jobPath, JsonSerializer.Serialize(new UsbReviewJob(1, "usb-native-readonly-review", nonce, source, reviewed)), token);
        var admin = new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
        var start = new ProcessStartInfo(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe")) { UseShellExecute = !admin, CreateNoWindow = admin, WindowStyle = ProcessWindowStyle.Hidden };
        if (!admin) start.Verb = "runas";
        start.ArgumentList.Add(Path.Combine(Backend.Root, "app/bin/Debug/net10.0-windows/OxpInstaller.dll")); start.ArgumentList.Add("--usb-review-helper"); start.ArgumentList.Add(jobPath);
        using var process = Process.Start(start) ?? throw new IOException("Read-only USB helper did not start.");
        using var cancel = token.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } });
        await process.WaitForExitAsync(); token.ThrowIfCancellationRequested();
        var resultPath = Path.Combine(directory, "result.json");
        if (!File.Exists(resultPath)) throw new IOException("Read-only USB helper ended without a result: " + directory);
        var result = JsonSerializer.Deserialize<UsbReviewResult>(await File.ReadAllTextAsync(resultPath)) ?? throw new IOException("Empty read-only USB result.");
        if ((process.ExitCode == 0) != (result.Status == "checked-readonly")) throw new IOException("USB metadata result/exit mismatch.");
        return new(directory, result);
    }
}