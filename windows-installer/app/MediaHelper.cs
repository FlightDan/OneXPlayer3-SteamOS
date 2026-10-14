using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;
namespace OxpInstaller;
public sealed record MediaJob(int Schema, string Kind, string Nonce, MediaSource Source, long Capacity, string Confirmation);
public sealed record MediaResult(string Status, long Written, long Verified, long Total, string? Error, string? Vhd, bool Detached, string Scope);
public sealed record MediaOperation(string Directory, MediaResult Result);
public static class MediaHelper
{
    public static string EventName(string nonce) => @"Local\Oxp3Media-" + nonce;
    public static bool PhysicalUsbAccepted => false;
    public static async Task<int> ExecuteAsync(string jobPath)
    {
        jobPath = Path.GetFullPath(jobPath); MediaSource.Ordinary(jobPath, InstallerWorkspace.DirectoryPath);
        if (Path.GetFileName(jobPath) != "media-job.json" || new FileInfo(jobPath).Length > 64 * 1024) throw new IOException("Invalid media job path/size.");
        using var jobFile = new FileStream(jobPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        var job = await JsonSerializer.DeserializeAsync<MediaJob>(jobFile) ?? throw new IOException("Empty media job.");
        if (job.Schema != 1 || job.Kind != "virtual-media-validation" || job.Confirmation != "erase-new-virtual-medium"
            || !Regex.IsMatch(job.Nonce, "^[0-9a-f]{32}$") || Path.GetFileName(Path.GetDirectoryName(jobPath)!) != "media-" + job.Nonce)
            throw new IOException("Unsupported or unconfirmed media job. Physical USB execution remains unaccepted.");
        if (job.Capacity < job.Source.Length || job.Capacity > 32L * 1024 * 1024 * 1024 || job.Capacity % 512 != 0) throw new IOException("Invalid virtual media capacity.");
        using var cancellation = EventWaitHandle.OpenExisting(EventName(job.Nonce));
        var directory = Path.GetDirectoryName(jobPath)!; var statusPath = Path.Combine(directory, "status.jsonl");
        MediaSource.Ordinary(statusPath, InstallerWorkspace.DirectoryPath, false);
        using var statusFile = new FileStream(statusPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        using var status = new StreamWriter(statusFile) { AutoFlush = true };
        MediaProgress current = new("validating", 0, 0, job.Source.Length); string outcome = "failed"; string? error = null, vhd = null; bool detached = false;
        void Report(MediaProgress progress) { current = progress; status.WriteLine(JsonSerializer.Serialize(progress)); }
        Report(current);
        VirtualMediaDisk? owned = null;
        try
        {
            if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) throw new IOException("Administrator media helper required.");
            using var source = MediaSource.Open(job.Source.Path);
            if (MediaSource.FromHandle(job.Source.Path, source) != job.Source) throw new IOException("Source identity/size/time/GPT changed after review.");
            if (cancellation.WaitOne(0)) throw new OperationCanceledException("Cancelled before target creation.");
            Report(new("checking-space", 0, 0, job.Source.Length));
            MediaSpace.Require(directory, job.Capacity);
            vhd = Path.Combine(directory, "media.vhd");
            owned = new VirtualMediaDisk(vhd, job.Capacity);
            NativeVolumes.RequireDifferentSource(source, owned.BoundDiskNumber());
            if (NativeVolumes.FindForDisk(owned.BoundDiskNumber(), owned.Size).Length != 0) throw new IOException("A freshly owned blank VHD unexpectedly exposes volumes.");
            using (var target = owned.OpenDevice())
                await AlignedMediaCopy.CopyAndVerifyAsync(source, target, job.Source.Length, owned.Size, Report, () => cancellation.WaitOne(0));
            outcome = "complete";
        }
        catch (OperationCanceledException exception) { error = exception.Message; outcome = "cancelled"; }
        catch (Exception exception) { error = exception.ToString(); outcome = "failed"; }
        finally
        {
            if (owned != null)
            {
                try { owned.Dispose(); detached = true; }
                catch (Exception cleanup) { outcome = "failed"; detached = false; error = (error == null ? "" : error + "\n") + "Owned VHD cleanup failed: " + cleanup; }
            }
            else detached = vhd == null; // No target was created; failed constructors remain unproven.
        }
        var result = new MediaResult(outcome, current.Written, current.Verified, job.Source.Length, error, vhd, detached,
            "New Windows VHD only; owned handle native device binding, aligned raw image copy, ordinary byte readback and handle-lifetime detach. No physical USB or existing disk execution.");
        var resultPath = Path.Combine(directory, "result.json"); MediaSource.Ordinary(resultPath, InstallerWorkspace.DirectoryPath, false);
        using var resultFile = new FileStream(resultPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        await JsonSerializer.SerializeAsync(resultFile, result); resultFile.Flush(true);
        Report(new(outcome, current.Written, current.Verified, job.Source.Length, error));
        return outcome == "complete" ? 0 : outcome == "cancelled" ? 2 : 1;
    }
}
public static class MediaWriterController
{
    public static async Task<MediaOperation> RunVirtualAsync(string image, Action<MediaProgress> report, CancellationToken token, Action<string>? prepared = null)
    {
        token.ThrowIfCancellationRequested(); var source = MediaSource.Read(image); var nonce = Guid.NewGuid().ToString("N");
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "media-" + nonce); System.IO.Directory.CreateDirectory(directory);
        var capacity = Math.Max(16L * 1024 * 1024, (source.Length + 1024 * 1024 - 1) / (1024 * 1024) * (1024 * 1024));
        MediaSpace.Require(directory, capacity); // Refuse an obviously full work volume before requesting UAC.
        var job = new MediaJob(1, "virtual-media-validation", nonce, source, capacity, "erase-new-virtual-medium");
        var jobPath = Path.Combine(directory, "media-job.json"); await File.WriteAllTextAsync(jobPath, JsonSerializer.Serialize(job), token);
        prepared?.Invoke(directory);
        using var signal = new EventWaitHandle(false, EventResetMode.ManualReset, MediaHelper.EventName(nonce));
        using var registration = token.Register(() => signal.Set());
        var elevated = new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
        var start = new ProcessStartInfo(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe"))
        { UseShellExecute = !elevated, CreateNoWindow = elevated, WindowStyle = ProcessWindowStyle.Hidden };
        if (!elevated) start.Verb = "runas";
        start.ArgumentList.Add(Path.Combine(Backend.Root, "app/bin/Debug/net10.0-windows/OxpInstaller.dll")); start.ArgumentList.Add("--media-helper"); start.ArgumentList.Add(jobPath);
        using var process = Process.Start(start) ?? throw new IOException("Media helper did not start.");
        var progressPath = Path.Combine(directory, "status.jsonl"); long position = 0; string pending = "";
        try
        {
        while (!process.HasExited)
        {
            if (File.Exists(progressPath))
            {
                using var file = new FileStream(progressPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                file.Position = position; using var reader = new StreamReader(file); pending += await reader.ReadToEndAsync(); position = file.Position;
                var lines = pending.Split('\n'); pending = lines[^1];
                foreach (var line in lines[..^1]) if (!string.IsNullOrWhiteSpace(line)) report(JsonSerializer.Deserialize<MediaProgress>(line)!);
            }
            await Task.Delay(50); // Cancellation signals the child; never kill while it cleans up.
        }
        await process.WaitForExitAsync(); var resultPath = Path.Combine(directory, "result.json");
        if (!File.Exists(resultPath)) throw new IOException("Media helper ended before publishing a result. " + directory);
        var result = JsonSerializer.Deserialize<MediaResult>(await File.ReadAllTextAsync(resultPath)) ?? throw new IOException("Empty media result.");
        if ((process.ExitCode == 0) != (result.Status == "complete") || (process.ExitCode == 2) != (result.Status == "cancelled")) throw new IOException("Media helper result/exit mismatch.");
        report(new(result.Status, result.Written, result.Verified, result.Total, result.Error));
        return new(directory, result);
        }
        finally { if (!process.HasExited) { signal.Set(); await process.WaitForExitAsync(); } }
    }
}
