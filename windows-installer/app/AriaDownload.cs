using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public sealed record DownloadOrigin(string Id, string Name, string English, string Version, string Url, string Note, string EnglishNote)
{
    public override string ToString() => InstallerI18n.Language == "en-US" ? English : Name;
}
public sealed record RemoteImage(string Url, long Length, string? ETag, string? Modified, bool Ranges, string FileName);
public sealed record ImageDownload(int Schema, string Id, string RequestedUrl, RemoteImage Remote, string Status, string? Error, DateTime Updated);
public sealed record DownloadProgress(long Completed, long Total, long Speed, string Status);

public static class AriaDownload
{
    public static string Root => Path.Combine(InstallerWorkspace.DirectoryPath, "downloads");
    public static string Executable => Path.Combine(Backend.Root, "runtime", "aria2", "aria2c.exe");
    public static DownloadOrigin[] Origins() => JsonSerializer.Deserialize<DownloadOrigin[]>(
        File.ReadAllText(Path.Combine(Backend.Root, "components", "download-sources.json")))!;
    public static Uri Address(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || !string.IsNullOrEmpty(uri.UserInfo)
            || !string.IsNullOrEmpty(uri.Fragment) || value.Any(char.IsControl)
            || !(uri.Scheme == "https" || uri.Scheme == "http" && uri.IsLoopback))
            throw new IOException("请输入 HTTPS 镜像直链。 / Enter an HTTPS image URL.");
        return uri;
    }
    public static string DirectoryFor(ImageDownload job)
    {
        if (job.Schema != 1 || !Regex.IsMatch(job.Id, "^[a-f0-9]{32}$")) throw new IOException("Invalid download task.");
        return Path.Combine(Root, job.Id);
    }
    private static string PathFor(ImageDownload job, string name)
    {
        var path = Path.Combine(DirectoryFor(job), name);
        MediaSource.Ordinary(path, InstallerWorkspace.DirectoryPath, false);
        return path;
    }
    public static string ResultPath(ImageDownload job) => PathFor(job, job.Remote.FileName);
    private static void Validate(ImageDownload job)
    {
        Address(job.RequestedUrl); Address(job.Remote.Url); _ = DirectoryFor(job);
        if (job.Remote.Length < 512 || job.Remote.Length > 64L * 1024 * 1024 * 1024
            || job.Remote.FileName is not ("recovery.img" or "recovery.img.bz2" or "recovery.img.zip")
            || job.Status is not ("ready" or "active" or "paused" or "failed" or "publishing" or "complete")
            || (job.Remote.ETag?.Any(char.IsControl) ?? false) || (job.Remote.Modified?.Any(char.IsControl) ?? false))
            throw new IOException("Invalid download metadata.");
    }
    private static void Save(ImageDownload job)
    {
        Validate(job); var path = PathFor(job, "download.json"); var temporary = PathFor(job, "download.json.tmp");
        using (var file = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
        { JsonSerializer.Serialize(file, job); file.Flush(true); }
        File.Move(temporary, path, true);
    }
    public static ImageDownload Load(string directory)
    {
        var path = Path.Combine(directory, "download.json"); MediaSource.Ordinary(path, Root);
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length > 65536) throw new IOException("Oversized download metadata.");
        var job = JsonSerializer.Deserialize<ImageDownload>(file) ?? throw new IOException("Missing download metadata.");
        Validate(job);
        if (!string.Equals(Path.GetFullPath(directory), DirectoryFor(job), StringComparison.OrdinalIgnoreCase)) throw new IOException("Download directory differs.");
        return job;
    }
    public static ImageDownload? Find(string url)
    {
        if (!Directory.Exists(Root)) return null;
        foreach (var directory in Directory.GetDirectories(Root).OrderByDescending(Directory.GetLastWriteTimeUtc))
        {
            try { var job = Load(directory); if (job.RequestedUrl == url) return job; }
            catch (Exception error) when (error is IOException or JsonException or UnauthorizedAccessException or ArgumentException) { }
        }
        return null;
    }
    public static async Task<RemoteImage> ProbeAsync(string url, CancellationToken token)
    {
        var uri = Address(url);
        var suffix = uri.AbsolutePath.EndsWith(".img.bz2", StringComparison.OrdinalIgnoreCase) ? ".img.bz2"
            : uri.AbsolutePath.EndsWith(".img.zip", StringComparison.OrdinalIgnoreCase) ? ".img.zip"
            : uri.AbsolutePath.EndsWith(".img", StringComparison.OrdinalIgnoreCase) ? ".img" : throw new IOException("直链必须以 .img、.img.bz2 或 .img.zip 结尾。 / Unsupported image URL.");
        using var handler = new HttpClientHandler { AllowAutoRedirect = false, AutomaticDecompression = DecompressionMethods.None };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(25) };
        for (var redirect = 0; redirect < 6; redirect++)
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, uri);
            request.Headers.Range = new RangeHeaderValue(0, 0); request.Headers.AcceptEncoding.ParseAdd("identity");
            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
            if ((int)response.StatusCode is 301 or 302 or 303 or 307 or 308)
            {
                uri = Address(new Uri(uri, response.Headers.Location ?? throw new IOException("Missing redirect destination.")).AbsoluteUri);
                continue;
            }
            response.EnsureSuccessStatusCode();
            var ranges = response.StatusCode == HttpStatusCode.PartialContent;
            var range = response.Content.Headers.ContentRange;
            var length = ranges ? range?.Length : response.Content.Headers.ContentLength;
            if (response.StatusCode is not (HttpStatusCode.OK or HttpStatusCode.PartialContent)
                || (ranges && (range?.From != 0 || range.To != 0)) || length is null or < 512 or > 68719476736
                || response.Content.Headers.ContentType?.MediaType?.Contains("html", StringComparison.OrdinalIgnoreCase) == true
                || response.Content.Headers.ContentEncoding.Any(e => e != "identity"))
                throw new IOException("服务器未返回有效的镜像文件信息。 / Invalid image response.");
            var tag = response.Headers.ETag;
            return new(uri.AbsoluteUri, length.Value, tag is { IsWeak: false } ? tag.ToString() : null,
                response.Content.Headers.LastModified?.ToString("R"), ranges, "recovery" + suffix);
        }
        throw new IOException("Too many image redirects.");
    }
    public static async Task<ImageDownload> CreateAsync(string url, CancellationToken token)
    {
        var remote = await ProbeAsync(url, token);
        var job = new ImageDownload(1, Guid.NewGuid().ToString("N"), url, remote, "ready", null, DateTime.UtcNow);
        var path = PathFor(job, "download.json"); Directory.CreateDirectory(Path.GetDirectoryName(path)!); Save(job); return job;
    }
    public static void CheckImage(string path, RemoteImage remote)
    {
        MediaSource.Ordinary(path, Root);
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length != remote.Length) throw new IOException("下载文件长度不符。 / Download length mismatch.");
        var header = new byte[512]; file.ReadExactly(header);
        var valid = remote.FileName.EndsWith(".bz2") ? header[0] == 'B' && header[1] == 'Z' && header[2] == 'h'
            : remote.FileName.EndsWith(".zip") ? header[0] == 'P' && header[1] == 'K' && header[2] == 3 && header[3] == 4
            : header[510] == 0x55 && header[511] == 0xaa;
        if (!valid) throw new IOException("下载内容不是所选镜像格式。 / Download is not the selected image format.");
    }
    private static ImageDownload Publish(ImageDownload job, Action<DownloadProgress> report)
    {
        var partial = PathFor(job, "payload.part"); var destination = ResultPath(job);
        if (File.Exists(destination)) CheckImage(destination, job.Remote);
        else
        {
            CheckImage(partial, job.Remote);
            using (var stream = new FileStream(partial, FileMode.Open, FileAccess.Write, FileShare.None)) stream.Flush(true);
            File.Move(partial, destination, false);
        }
        job = job with { Status = "complete", Error = null, Updated = DateTime.UtcNow }; Save(job);
        report(new(job.Remote.Length, job.Remote.Length, 0, "complete")); return job;
    }
    public static async Task<ImageDownload> RunAsync(ImageDownload selected, Action<DownloadProgress> report, CancellationToken token)
    {
        Validate(selected);
        using var lease = new FileStream(PathFor(selected, "operation.lock"), FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.DeleteOnClose);
        var job = Load(DirectoryFor(selected));
        if (job.RequestedUrl != selected.RequestedUrl || job.Remote != selected.Remote) throw new IOException("Download task changed.");
        if (job.Status == "complete") { CheckImage(ResultPath(job), job.Remote); report(new(job.Remote.Length, job.Remote.Length, 0, "complete")); return job; }
        if (job.Status == "publishing") return Publish(job, report);
        var partial = PathFor(job, "payload.part"); var control = PathFor(job, "payload.part.aria2");
        var hasPartial = File.Exists(partial);
        var current = await ProbeAsync(job.RequestedUrl, token);
        if (current != job.Remote) throw new IOException("远端文件已变化，请重新下载。 / Remote file changed; start a new download.");
        if (hasPartial && (!current.Ranges || current.ETag == null && current.Modified == null))
            throw new IOException("此来源不能安全续传，请重新下载。 / This source cannot resume; start a new download.");
        if (hasPartial && !File.Exists(control)) throw new IOException("续传记录缺失，请重新下载。 / Missing resume control file.");
        if (new DriveInfo(Path.GetPathRoot(Root)!).AvailableFreeSpace < current.Length + 64L * 1024 * 1024)
            throw new IOException("下载目录空间不足。 / Insufficient download space.");
        // All source changes create separate tasks; partial bytes never cross sources.
        job = job with { Status = "active", Error = null, Updated = DateTime.UtcNow }; Save(job);
        try
        {
            await using (var worker = await AriaWorker.StartAsync(token))
            {
                var options = new Dictionary<string, object> {
                    ["dir"] = DirectoryFor(job), ["out"] = "payload.part", ["split"] = current.Ranges ? "4" : "1",
                    ["max-connection-per-server"] = current.Ranges ? "4" : "1" };
                if (current.ETag != null) options["header"] = new[] { "If-Match: " + current.ETag };
                else if (current.Modified != null) options["header"] = new[] { "If-Unmodified-Since: " + current.Modified };
                var gid = (await worker.CallAsync("aria2.addUri", new object[] { new[] { current.Url }, options }, token)).GetString()!;
                while (true)
                {
                    token.ThrowIfCancellationRequested();
                    var data = await worker.CallAsync("aria2.tellStatus", new object[] { gid, new[] { "status", "totalLength", "completedLength", "downloadSpeed", "errorCode" } }, token);
                    var status = data.GetProperty("status").GetString();
                    long Number(string key) => long.Parse(data.GetProperty(key).GetString()!, System.Globalization.CultureInfo.InvariantCulture);
                    var total = Number("totalLength"); var done = Number("completedLength");
                    if (total != 0 && total != current.Length) throw new IOException("Download size changed.");
                    report(new(done, current.Length, Number("downloadSpeed"), status!));
                    if (status == "error") throw new IOException("aria2 下载失败，错误代码 / error code: " + data.GetProperty("errorCode").GetString());
                    if (status == "complete")
                    {
                        if (done != current.Length) throw new IOException("aria2 returned an incomplete result.");
                        break;
                    }
                    await Task.Delay(250, token);
                }
            }
            // Journal the completed transfer before renaming; reopening can finish either side of the rename.
            job = job with { Status = "publishing", Updated = DateTime.UtcNow }; Save(job);
            return Publish(job, report);
        }
        catch (Exception error)
        {
            if (job.Status == "publishing") throw;
            job = job with { Status = error is OperationCanceledException ? "paused" : "failed", Error = error.Message, Updated = DateTime.UtcNow };
            Save(job); throw;
        }
    }
}

internal sealed class AriaWorker : IAsyncDisposable
{
    private readonly Process process;
    private readonly HttpClient client;
    private readonly string secret;
    private readonly Task<string> stdout, stderr;
    private AriaWorker(Process process, HttpClient client, string secret)
    { this.process = process; this.client = client; this.secret = secret; stdout = process.StandardOutput.ReadToEndAsync(); stderr = process.StandardError.ReadToEndAsync(); }
    public static async Task<AriaWorker> StartAsync(CancellationToken token)
    {
        if (!File.Exists(AriaDownload.Executable)) throw new IOException("缺少内置 aria2c。 / Bundled aria2c is missing.");
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port; listener.Stop();
        var secret = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
        var start = new ProcessStartInfo(AriaDownload.Executable) {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            WorkingDirectory = Path.GetDirectoryName(AriaDownload.Executable)! };
        foreach (var arg in new[] { "--no-conf=true", "--no-netrc=true", "--enable-rpc=true", "--rpc-listen-all=false",
            "--rpc-allow-origin-all=false", "--rpc-listen-port=" + port, "--rpc-secret=" + secret,
            "--stop-with-process=" + Environment.ProcessId, "--disable-ipv6=true", "--enable-dht=false", "--enable-dht6=false",
            "--enable-peer-exchange=false", "--bt-enable-lpd=false", "--follow-torrent=false", "--follow-metalink=false",
            "--check-integrity=false", "--file-allocation=none", "--auto-file-renaming=false", "--allow-overwrite=false",
            "--continue=true", "--always-resume=true", "--max-resume-failure-tries=0", "--auto-save-interval=1",
            "--max-concurrent-downloads=1", "--connect-timeout=15", "--timeout=30", "--max-tries=3", "--retry-wait=2",
            "--console-log-level=error", "--summary-interval=0", "--download-result=hide", "--check-certificate=true" })
            start.ArgumentList.Add(arg);
        var process = Process.Start(start) ?? throw new IOException("Could not start aria2c.");
        var client = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri($"http://127.0.0.1:{port}/jsonrpc"), Timeout = TimeSpan.FromSeconds(3) };
        var worker = new AriaWorker(process, client, secret);
        try
        {
            for (var attempt = 0; attempt < 40; attempt++)
            {
                token.ThrowIfCancellationRequested();
                if (process.HasExited) throw new IOException("aria2c 启动失败 / startup failed: " + process.ExitCode);
                try { await worker.CallAsync("aria2.getVersion", [], token); return worker; }
                catch (HttpRequestException) { await Task.Delay(100, token); }
            }
            throw new IOException("aria2c startup timeout.");
        }
        catch { await worker.DisposeAsync(); throw; }
    }
    public async Task<JsonElement> CallAsync(string method, object[] values, CancellationToken token)
    {
        var args = new object[values.Length + 1]; args[0] = "token:" + secret; values.CopyTo(args, 1);
        using var body = new StringContent(JsonSerializer.Serialize(new { jsonrpc = "2.0", id = "installer", method, @params = args }), System.Text.Encoding.UTF8, "application/json");
        using var response = await client.PostAsync("", body, token); response.EnsureSuccessStatusCode();
        using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token));
        if (json.RootElement.TryGetProperty("error", out var error)) throw new IOException("aria2 RPC error " + error.GetProperty("code"));
        return json.RootElement.GetProperty("result").Clone();
    }
    public async ValueTask DisposeAsync()
    {
        try
        {
            if (!process.HasExited)
            {
                try { await CallAsync("aria2.shutdown", [], CancellationToken.None); } catch (Exception error) when (error is HttpRequestException or TaskCanceledException or IOException) { }
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
                try { await process.WaitForExitAsync(timeout.Token); }
                catch (OperationCanceledException) { process.Kill(true); await process.WaitForExitAsync(); }
            }
            await Task.WhenAll(stdout, stderr);
        }
        finally { client.Dispose(); process.Dispose(); }
    }
}
