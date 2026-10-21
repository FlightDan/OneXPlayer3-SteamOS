using System.IO;
using System.Net.Http;
using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public sealed record OfficialPreparationProgress(string Step, string Message, double Fraction);

public static class OfficialSystem
{
    public static async Task<string> CheckPreparationAsync(string recovery,Action<string> log,CancellationToken token)
    {
        var directory=Path.Combine(InstallationController.Work,"accepted-3.10-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
        var fixture=await Backend.CreateFixtureAsync(log,token);
        await Backend.GuestAsync("deployment-test",recovery,false,log,token,fixture:fixture);
        var image=Path.Combine(directory,"prepared.img");
        await Backend.ProcessAsync(Path.Combine(Backend.Root,"runtime/qemu-min/qemu-img.exe"),["convert","-O","raw",QcowReadOnlyGraph.Filename(fixture),image],log,token);
        var options=System.Text.Json.JsonSerializer.Serialize(InstallerOptions.Defaults,new System.Text.Json.JsonSerializerOptions{PropertyNamingPolicy=System.Text.Json.JsonNamingPolicy.SnakeCaseLower});
        await File.WriteAllTextAsync(Path.Combine(directory,"options.json"),options,token);
        await Backend.GuestAsync("integration",image,true,log,token,selection:options);
        await Backend.GuestAsync("integration-verify",image,false,log,token,selection:options);
        await Backend.GuestAsync("physical-readiness",image,false,log,token);
        var boot=await VirtualBoot.IntegratedImageAsync(image,log,token);
        await File.WriteAllTextAsync(Path.Combine(directory,"result.json"),System.Text.Json.JsonSerializer.Serialize(new{passed=true,image,boot,scope="Official 3.10 preparation, selected component staging, readonly inspection and virtual UEFI login. No handheld boot acceptance."}),token);
        return directory;
    }
    public const string Version="3.10";
    public const string Build="20260924.1000";
    public const string BaseUrl="https://steamdeck-images.steamos.cloud/steamdeck/20260924.1000/steamdeck-20260924.1000-3.10.0";
    internal const long RootSize = 5368709120L;
    private static string Cache => Path.Combine(InstallerWorkspace.DirectoryPath, "steamos-3.10");
    internal static bool IsBundleReady()
    {
        try
        {
            foreach (var name in new[] { "bundle-ready.txt", "system.raucb", "rootfs.img.caibx", "manifest.raucm" })
            {
                var path = Path.Combine(Cache, name); MediaSource.Ordinary(path, InstallationController.Work);
                if (new FileInfo(path).Length == 0) return false;
            }
            var marker = Path.Combine(Cache, "bundle-ready.txt");
            return new FileInfo(marker).Length < 1024 && File.ReadAllText(marker) == BaseUrl;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return false; }
    }
    internal static bool HasPreparedSource() => IsBundleReady() || IsCached();
    internal static string RequirePreparedSource()
    {
        if (IsBundleReady()) return Path.Combine(Cache, "system.raucb");
        return RequireCachedRoot();
    }
    internal static async Task<string> StageBundleAsync(Action<string> log, CancellationToken token,
        Action<OfficialPreparationProgress>? report = null, string? localBundle = null, bool fresh = false)
    {
        Directory.CreateDirectory(Cache);
        var leasePath = Path.Combine(Cache, "download.lock"); MediaSource.Ordinary(leasePath, InstallationController.Work, false);
        using var lease = new FileStream(leasePath, FileMode.Create, FileAccess.ReadWrite, FileShare.None);
        if (localBundle == null && !fresh && HasPreparedSource()) return RequirePreparedSource();
        var staging = Path.Combine(Cache, "bundle-stage-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(staging);
        var bundle = Path.Combine(staging, "system.raucb");
        try
        {
            if (localBundle != null)
            {
                report?.Invoke(new("bundle", PartitionInventory.L("正在读取本地更新包…", "Reading the local update bundle…"), 0));
                using var source = new FileStream(localBundle, FileMode.Open, FileAccess.Read, FileShare.Read);
                using var target = new FileStream(bundle, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                await source.CopyToAsync(target, token);
            }
            else
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(3) };
                using var response = await client.GetAsync(BaseUrl + ".raucb", HttpCompletionOption.ResponseHeadersRead, token);
                response.EnsureSuccessStatusCode();
                using var source = await response.Content.ReadAsStreamAsync(token);
                using var target = new FileStream(bundle, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                await CopyDownloadAsync(source, target, response.Content.Headers.ContentLength, (bytes, total, speed) =>
                    report?.Invoke(new("bundle", PartitionInventory.L("正在下载 3.10 更新包", "Downloading the 3.10 update bundle")
                        + $" · {bytes / 1048576d:F2} MiB · {speed / 1048576d:F2} MiB/s", total is > 0 ? bytes / (double)total.Value * .9 : 0)), token);
            }
            await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/archive/7z.exe"),
                ["e", bundle, "-o" + staging, "-y", "rootfs.img.caibx", "manifest.raucm"], log, token);
            var manifest = await File.ReadAllTextAsync(Path.Combine(staging, "manifest.raucm"), token);
            if (!manifest.Contains("compatible=steamos-amd64") || !Regex.IsMatch(manifest, @"(?m)^version=3\.10(?:\.0)?\r?$")
                || !manifest.Contains("filename=rootfs.img.caibx") || new FileInfo(Path.Combine(staging, "rootfs.img.caibx")).Length == 0)
                throw new IOException("Unexpected official update manifest.");
            foreach (var name in new[] { "bundle-ready.txt", "complete.txt", "system.raucb", "rootfs.img.caibx", "manifest.raucm" })
                MediaSource.Ordinary(Path.Combine(Cache, name), InstallationController.Work, false);
            token.ThrowIfCancellationRequested();
            File.Delete(Path.Combine(Cache, "bundle-ready.txt")); File.Delete(Path.Combine(Cache, "complete.txt"));
            foreach (var name in new[] { "system.raucb", "rootfs.img.caibx", "manifest.raucm" })
                File.Move(Path.Combine(staging, name), Path.Combine(Cache, name), true);
            await File.WriteAllTextAsync(Path.Combine(Cache, "bundle-ready.txt"), BaseUrl, token);
            report?.Invoke(new("bundle", PartitionInventory.L("更新包已就绪，开始安装后重建系统镜像。", "Update bundle ready. The system image will be rebuilt after installation starts."), 1));
            return Path.Combine(Cache, "system.raucb");
        }
        finally { Directory.Delete(staging, true); }
    }
    internal static bool IsCached()
    {
        var root = Path.Combine(Cache, "rootfs.img"); var complete = Path.Combine(Cache, "complete.txt");
        try
        {
            MediaSource.Ordinary(root, InstallationController.Work, false);
            MediaSource.Ordinary(complete, InstallationController.Work, false);
            return File.Exists(root) && new FileInfo(root).Length == RootSize && File.Exists(complete)
                && new FileInfo(complete).Length < 1024 && File.ReadAllText(complete) == BaseUrl;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return false; }
    }
    internal static string RequireCachedRoot()
    {
        if (!IsCached()) throw new IOException(PartitionInventory.L(
            "请先在“准备系统”页面下载并准备官方 SteamOS 3.10。", "Download and prepare official SteamOS 3.10 on the Prepare system page first."));
        return Path.Combine(Cache, "rootfs.img");
    }
    internal static double? AssemblyFraction(string line)
    {
        var match = Regex.Match(line, @"^\s*Attempt \d+: Assembling\s+([0-9]+(?:\.[0-9]+)?)%");
        return match.Success && double.TryParse(match.Groups[1].Value, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var percent)
            && percent is >= 0 and <= 100 ? percent / 100 : null;
    }
    internal static async Task CopyDownloadAsync(Stream source, Stream destination, long? total,
        Action<long, long?, double> report, CancellationToken token)
    {
        if (total <= 0) total = null;
        var watch = Stopwatch.StartNew(); var last = TimeSpan.Zero; long received = 0, previous = 0;
        var buffer = new byte[128 * 1024];
        report(0, total, 0);
        while (await source.ReadAsync(buffer, token) is var count && count > 0)
        {
            await destination.WriteAsync(buffer.AsMemory(0, count), token); received += count;
            if (total.HasValue && received > total.Value) throw new IOException("Official update exceeded its declared download size.");
            if (watch.Elapsed - last < TimeSpan.FromMilliseconds(500)) continue;
            report(received, total, (received - previous) / (watch.Elapsed - last).TotalSeconds);
            last = watch.Elapsed; previous = received;
        }
        if (total.HasValue && received != total.Value) throw new IOException("Official update download was incomplete.");
        await destination.FlushAsync(token);
        report(received, total, received / Math.Max(.001, watch.Elapsed.TotalSeconds));
    }
    public static async Task<string> DownloadAsync(Action<string> log, CancellationToken token,
        Action<OfficialPreparationProgress>? report = null, string? localBundle = null, bool fresh = false)
    {
        var cache = Cache; Directory.CreateDirectory(cache);
        MediaSource.Ordinary(Path.Combine(cache, "download.lock"), InstallationController.Work, false);
        using var lease=new FileStream(Path.Combine(cache,"download.lock"),FileMode.Create,FileAccess.ReadWrite,FileShare.None);
        var root=Path.Combine(cache,"rootfs.img");var bundle=Path.Combine(cache,"system.raucb");
        var index=Path.Combine(cache,"rootfs.img.caibx");var complete=Path.Combine(cache,"complete.txt");
        foreach(var path in new[]{root,bundle,index,complete})MediaSource.Ordinary(path,InstallationController.Work,false);
        if (fresh || localBundle != null) File.Delete(complete);
        if (fresh) File.Delete(root);
        if (!IsCached())
        {
            MediaSpace.RequireAvailable(cache, (ulong)RootSize + 512ul * 1024 * 1024);
            log("Preparing official SteamOS 3.10 build20260924.1000 root image…");
            report?.Invoke(new("01.02.01", localBundle != null
                ? PartitionInventory.L("正在读取本地更新包…", "Reading the local update bundle…")
                : PartitionInventory.L("正在连接官方更新包下载…", "Connecting to the official update download…"), 0));
            using var client=new HttpClient{Timeout=TimeSpan.FromMinutes(3)};
            if (localBundle != null)
            {
                if (!string.Equals(Path.GetFullPath(localBundle), Path.GetFullPath(bundle), StringComparison.OrdinalIgnoreCase))
                {
                    using var source = new FileStream(localBundle, FileMode.Open, FileAccess.Read, FileShare.Read);
                    using var target = new FileStream(bundle, FileMode.Create, FileAccess.Write, FileShare.None);
                    await source.CopyToAsync(target, token);
                }
            }
            else using(var response=await client.GetAsync(BaseUrl+".raucb",HttpCompletionOption.ResponseHeadersRead,token))
            {
                response.EnsureSuccessStatusCode();
                using var file=new FileStream(bundle,FileMode.Create,FileAccess.Write,FileShare.None);
                using var source = await response.Content.ReadAsStreamAsync(token);
                await CopyDownloadAsync(source, file, response.Content.Headers.ContentLength, (received, total, speed) =>
                {
                    var fraction = total is > 0 ? received / (double)total.Value : 0;
                    var detail = total is > 0 ? $"{fraction * 100:F1}% · {received / 1048576d:F1} / {total.Value / 1048576d:F1} MiB"
                        : $"{received / 1048576d:F1} MiB";
                    report?.Invoke(new("01.02.01", PartitionInventory.L("下载官方更新包", "Downloading the official update")
                        + $"\n{detail} · {speed / 1048576d:F2} MiB/s", .1 * fraction));
                }, token);
                file.Flush(true);
            }
            report?.Invoke(new("01.02.02", PartitionInventory.L("正在提取并检查更新索引…", "Extracting and checking the update index…"), .1));
            await Backend.ProcessAsync(Path.Combine(Backend.Root,"runtime/archive/7z.exe"),["e",bundle,"-o"+cache,"-y","rootfs.img.caibx","manifest.raucm"],log,token);
            var manifest=await File.ReadAllTextAsync(Path.Combine(cache,"manifest.raucm"),token);
            if(!manifest.Contains("compatible=steamos-amd64") || !manifest.Contains("version=3.10") || !manifest.Contains("filename=rootfs.img.caibx"))throw new IOException("Unexpected official update manifest.");
            report?.Invoke(new("01.02.03", PartitionInventory.L("正在检查已有数据并重建系统镜像（5 GiB）…", "Checking existing data and rebuilding the system image (5 GiB)…"), .1));
            await Backend.ProcessAsync(Path.Combine(Backend.Root,"runtime/desync/desync.exe"),["extract","-k","-n","12","-s",BaseUrl+".castr","--print-stats",index,root], line =>
            {
                log(line);
                if (AssemblyFraction(line) is double fraction)
                    report?.Invoke(new("01.02.03", PartitionInventory.L("重建系统镜像", "Rebuilding the system image")
                        + $"\n{fraction * 100:F2}% · {fraction * RootSize / 1073741824d:F2} / 5.00 GiB"
                        + PartitionInventory.L("（已重建）", " (rebuilt)"), .1 + .7 * fraction));
            },token, new Dictionary<string, string> { ["DESYNC_ENABLE_PARSABLE_PROGRESS"] = "1" });
            if(new FileInfo(root).Length!=RootSize)throw new IOException("Official root image has an unexpected size.");
            await File.WriteAllTextAsync(complete,BaseUrl,token);
            File.Delete(Path.Combine(cache, "bundle-ready.txt"));
        }
        report?.Invoke(new("01.02.03", PartitionInventory.L("官方 SteamOS 3.10 已缓存，可开始安装。", "Official SteamOS 3.10 is cached and ready for installation."), 1));
        return root;
    }
    internal static async Task<string> ImportRootAsync(string sourcePath, CancellationToken token,
        Action<OfficialPreparationProgress>? report = null)
    {
        using var source = new FileStream(sourcePath, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (source.Length != RootSize) throw new IOException(PartitionInventory.L("请选择重建后的 5 GiB rootfs.img 系统分区镜像。", "Select the rebuilt 5 GiB rootfs.img system partition image."));
        source.Position = 0x10040;
        var magic = new byte[8]; await source.ReadExactlyAsync(magic, token);
        if (System.Text.Encoding.ASCII.GetString(magic) != "_BHRfS_M") throw new IOException(PartitionInventory.L("这不是 Btrfs 系统分区镜像，请选择 rootfs.img。", "This is not a Btrfs system partition image. Select rootfs.img."));
        source.Position = 0;
        Directory.CreateDirectory(Cache);
        var root = Path.Combine(Cache, "rootfs.img"); var complete = Path.Combine(Cache, "complete.txt");
        var pending = Path.Combine(Cache, "importing.img"); var leasePath = Path.Combine(Cache, "download.lock");
        foreach (var path in new[] { root, complete, pending, leasePath }) MediaSource.Ordinary(path, InstallationController.Work, false);
        using var lease = new FileStream(leasePath, FileMode.Create, FileAccess.ReadWrite, FileShare.None);
        if (!string.Equals(Path.GetFullPath(sourcePath), Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase))
        {
            MediaSpace.RequireAvailable(Cache, (ulong)RootSize);
            try
            {
                using (var target = new FileStream(pending, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    await CopyDownloadAsync(source, target, RootSize, (bytes, total, speed) =>
                        report?.Invoke(new("local", PartitionInventory.L("正在导入本地 3.10 镜像", "Importing the local 3.10 image") + $" · {bytes * 100d / RootSize:F1}%", bytes / (double)RootSize)), token);
                    target.Flush(true);
                }
                File.Delete(complete);
                File.Move(pending, root, true);
            }
            finally { File.Delete(pending); }
        }
        await File.WriteAllTextAsync(complete, BaseUrl, token);
        File.Delete(Path.Combine(Cache, "bundle-ready.txt"));
        return root;
    }
    public static async Task<string> PrepareAsync(string recovery,string directory,Action<string> log,CancellationToken token,
        Action<OfficialPreparationProgress>? report = null)
    {
        RecoveryImage.ValidateRaw(recovery);
        var source = RequirePreparedSource();
        var root = source.EndsWith(".raucb", StringComparison.OrdinalIgnoreCase)
            ? await DownloadAsync(log, token, report, source) : source;
        report?.Invoke(new("01.02.04", PartitionInventory.L("已使用本地 3.10 缓存，正在转换恢复镜像…", "Using the local 3.10 cache; converting the recovery image…"), .8));
        var output=Path.Combine(directory,"recovery-3.10.img");
        await RawImageStaging.ConvertAsync(recovery,output,log,token);
        report?.Invoke(new("01.02.05", PartitionInventory.L("正在虚拟机中整合 SteamOS 3.10，等待系统处理…", "Integrating SteamOS 3.10 in the virtual machine; waiting for system processing…"), .9));
        // The VM checks actual os-release and kernel before modifying only this new ordinary image.
        await Backend.GuestAsync("upgrade-source",output,true,log,token,updateRoot:root);
        report?.Invoke(new("01.02.05", PartitionInventory.L("SteamOS 3.10 整合完成。", "SteamOS 3.10 integration completed."), 1));
        return output;
    }
}
