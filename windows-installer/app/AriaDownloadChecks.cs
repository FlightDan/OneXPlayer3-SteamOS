using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace OxpInstaller;

public static class AriaDownloadChecks
{
    private sealed class Server : IAsyncDisposable
    {
        private readonly TcpListener listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource stop = new();
        private readonly ConcurrentBag<Task> requests = new();
        private readonly Task accept;
        public readonly byte[] Bytes = new byte[32 * 1024 * 1024];
        public readonly ConcurrentQueue<long> Starts = new();
        public string ETag = "\"fixture-v1\"";
        public string Url { get; }
        public Server()
        {
            for (var i = 0; i < Bytes.Length; i++) Bytes[i] = (byte)(i * 17 + 3);
            Bytes[510] = 0x55; Bytes[511] = 0xaa;
            listener.Start(); Url = $"http://127.0.0.1:{((IPEndPoint)listener.LocalEndpoint).Port}";
            accept = Task.Run(async () => {
                try { while (!stop.IsCancellationRequested) { var client = await listener.AcceptTcpClientAsync(stop.Token); requests.Add(Serve(client)); } }
                catch (OperationCanceledException) { }
            });
        }
        private async Task Serve(TcpClient client)
        {
            using (client)
            try
            {
                var stream = client.GetStream(); using var reader = new StreamReader(stream, Encoding.ASCII, false, 4096, true);
                var line = await reader.ReadLineAsync(stop.Token); if (line == null) return;
                var path = line.Split(' ')[1]; var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                while (!string.IsNullOrEmpty(line = await reader.ReadLineAsync(stop.Token)))
                { var colon = line.IndexOf(':'); if (colon > 0) headers[line[..colon]] = line[(colon + 1)..].Trim(); }
                if (path.StartsWith("/missing")) { await stream.WriteAsync("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"u8.ToArray(), stop.Token); return; }
                if (headers.TryGetValue("If-Match", out var tag) && tag != ETag) { await stream.WriteAsync("HTTP/1.1 412 Precondition Failed\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"u8.ToArray(), stop.Token); return; }
                var ranged = !path.StartsWith("/noranges") && headers.TryGetValue("Range", out _);
                long start = 0, end = Bytes.Length - 1;
                if (ranged)
                {
                    var bounds = headers["Range"]["bytes=".Length..].Split('-'); start = long.Parse(bounds[0]);
                    if (bounds.Length > 1 && bounds[1].Length > 0) end = Math.Min(end, long.Parse(bounds[1]));
                }
                Starts.Enqueue(start);
                var response = $"HTTP/1.1 {(ranged ? "206 Partial Content" : "200 OK")}\r\nContent-Length: {end - start + 1}\r\nContent-Type: {(path.StartsWith("/html") ? "text/html" : "application/octet-stream")}\r\nETag: {ETag}\r\nConnection: close\r\n"
                    + (ranged ? $"Content-Range: bytes {start}-{end}/{Bytes.Length}\r\n" : "") + "\r\n";
                await stream.WriteAsync(Encoding.ASCII.GetBytes(response), stop.Token);
                for (long at = start; at <= end;)
                {
                    var count = (int)Math.Min(65536, end - at + 1);
                    await stream.WriteAsync(Bytes.AsMemory((int)at, count), stop.Token); at += count;
                    if (end > 1) await Task.Delay(10, stop.Token);
                }
            }
            catch (Exception error) when (error is IOException or OperationCanceledException or SocketException) { }
        }
        public async ValueTask DisposeAsync()
        { stop.Cancel(); listener.Stop(); await accept; await Task.WhenAll(requests); stop.Dispose(); }
    }
    private static async Task CheckPanelAsync(Server server, List<string> events)
    {
        void Require(bool ok, string name) { if (!ok) throw new IOException("CHECK FAILED: " + name); events.Add(name); }
        var window = new MainWindow(rehearsal: true);
        ((PartitionPicker)window.FindName("PartitionSelector")).AutomaticReadEnabled = false;
        var host = (System.Windows.Controls.StackPanel)window.FindName("DownloadHost");
        var panel = (ImageDownloadPanel)host.Children[0];
        var body = (System.Windows.Controls.StackPanel)panel.Content;
        IEnumerable<T> Controls<T>(System.Windows.DependencyObject node) where T : System.Windows.DependencyObject
        {
            if (node is T match) yield return match;
            foreach (var child in System.Windows.LogicalTreeHelper.GetChildren(node).OfType<System.Windows.DependencyObject>())
                foreach (var descendant in Controls<T>(child)) yield return descendant;
        }
        // Address and consent are nested in the copy/terms action rows.
        var source = Controls<System.Windows.Controls.ComboBox>(body).Single();
        var address = Controls<System.Windows.Controls.TextBox>(body).Single();
        var agreement = Controls<System.Windows.Controls.CheckBox>(body).Single();
        var next = (System.Windows.Controls.Button)window.FindName("NextButton");
        Require(address.IsReadOnly && agreement.IsChecked != true, "native-panel-official-readonly-consent-unchecked");
        source.SelectedIndex = source.Items.Count - 1; address.Text = server.Url + "/panel.img";
        Require(!address.IsReadOnly, "native-panel-custom-url-editable");
        var count = server.Starts.Count;
        await panel.DownloadAsync(false);
        Require(server.Starts.Count == count && !panel.IsBusy, "native-panel-no-download-without-consent");
        agreement.IsChecked = true;
        var run = panel.DownloadAsync(false);
        Require(panel.IsBusy && !next.IsEnabled && !source.IsEnabled, "native-panel-busy-locks-navigation-and-source");
        await run;
        var path = ((System.Windows.Controls.TextBox)window.FindName("ImagePath")).Text;
        Require(!panel.IsBusy && next.IsEnabled && File.Exists(path)
            && File.ReadAllBytes(path).AsSpan().SequenceEqual(server.Bytes), "native-panel-download-selects-complete-image-and-unlocks");
    }
    public static async Task<string> OfficialAsync()
    {
        var job = await AriaDownload.CreateAsync(AriaDownload.Origins()[0].Url, CancellationToken.None);
        var counts = new List<long>();
        for (var pass = 0; pass < 2; pass++)
        {
            using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(60));
            long done = 0; var threshold = (counts.LastOrDefault() + 2L * 1024 * 1024);
            try { await AriaDownload.RunAsync(job, p => { done = p.Completed; if (done >= threshold) cancel.Cancel(); }, cancel.Token); }
            catch (OperationCanceledException) { }
            job = AriaDownload.Load(AriaDownload.DirectoryFor(job));
            if (job.Status != "paused" || done < threshold || !File.Exists(Path.Combine(AriaDownload.DirectoryFor(job), "payload.part.aria2")))
                throw new IOException("Official HTTPS pause/resume did not reach the requested progress.");
            counts.Add(done);
        }
        var report = Path.Combine(Backend.Root, "logs", "aria2-official-checks.json");
        await File.WriteAllTextAsync(report, JsonSerializer.Serialize(new { passed = true, url = job.RequestedUrl, counts,
            directory = AriaDownload.DirectoryFor(job), scope = "Bundled aria2 HTTPS sample transfer and new-process resume; not a full system-image download." },
            new JsonSerializerOptions { WriteIndented = true }));
        return report;
    }
    private static async Task CheckAdvancedAsync(Server server, List<string> events)
    {
        void Require(bool ok, string name) { if (!ok) throw new IOException("CHECK FAILED: " + name); events.Add(name); }
        var language = InstallerI18n.Language;
        InstallerI18n.SetLanguage("zh-CN");
        var window = new AdvancedWindow();
        InstallerI18n.SetLanguage(language);
        var selector = (System.Windows.Controls.ComboBox)window.FindName("DownloadSourceSelector");
        var address = (System.Windows.Controls.TextBox)window.FindName("CustomDownloadUrl");
        var status = (System.Windows.Controls.TextBlock)window.FindName("DownloadStatus");
        var progress = (System.Windows.Controls.ProgressBar)window.FindName("DownloadProgress");
        var bottom = (System.Windows.Controls.ProgressBar)window.FindName("Progress");
        var button = (System.Windows.Controls.Button)window.FindName("DownloadButton");
        System.Windows.Controls.ComboBoxItem Item(string path) => new() { Content = path,
            Tag = new DownloadOrigin(path, path, path, "3.8.14", server.Url + path, "", "") };
        var dead = Item("/missing.img"); var live = Item("/advanced.img");
        selector.Items.Clear(); selector.Items.Add(dead); selector.Items.Add(live); selector.SelectedIndex = 0;
        await window.ProbeDownloadSourcesAsync();
        Require(selector.SelectedItem == live && button.IsEnabled, "advanced-auto-selects-live-image-over-404");
        string? copied = null; var requestsBeforeCopy = server.Starts.Count;
        window.CopyDownloadAddressTo(value => copied = value);
        Require(copied == server.Url + "/advanced.img" && server.Starts.Count == requestsBeforeCopy, "advanced-copy-selected-source-without-downloading");
        var pending = window.ProbeDownloadSourcesAsync(); selector.SelectedItem = dead; await pending;
        Require(selector.SelectedItem == dead, "advanced-probe-preserves-manual-selection");
        selector.Items.Remove(live); await window.ProbeDownloadSourcesAsync();
        Require(selector.SelectedItem == dead && button.IsEnabled && !string.IsNullOrEmpty(dead.ToolTip?.ToString()), "advanced-all-unavailable-explained-retry-enabled");
        var custom = new System.Windows.Controls.ComboBoxItem { Content = "自定义镜像源" };
        selector.Items.Add(custom); selector.SelectedItem = custom; address.Text = server.Url + "/advanced.img";
        Require(address.Visibility == System.Windows.Visibility.Visible, "advanced-custom-source-shows-url");
        copied = null; window.CopyDownloadAddressTo(value => copied = value);
        Require(copied == address.Text, "advanced-copy-custom-url");
        address.Text = "file:///C:/invalid.img"; copied = null; window.CopyDownloadAddressTo(value => copied = value);
        Require(copied == null, "advanced-copy-invalid-url-refused");
        address.Text = server.Url + "/advanced.img";
        var run = window.DownloadRecoveryAsync();
        Require(!selector.IsEnabled && progress.IsIndeterminate && !bottom.IsIndeterminate, "advanced-download-uses-local-progress-and-locks-source");
        await run;
        var path = ((System.Windows.Controls.TextBox)window.FindName("SourcePath")).Text;
        Require(File.Exists(path) && File.ReadAllBytes(path).AsSpan().SequenceEqual(server.Bytes)
            && progress.Value == 100 && bottom.Value == 0 && selector.IsEnabled, "advanced-download-selects-image-and-completes-local-progress");
        await window.DownloadRecoveryAsync();
        Require(progress.Value == 100, "advanced-reuses-complete-download");
        var root = (System.Windows.FrameworkElement)window.Content;
        root.Measure(new System.Windows.Size(1024, 800)); root.Arrange(new System.Windows.Rect(0, 0, 1024, 800)); root.UpdateLayout();
        var buttonAt = button.TranslatePoint(new System.Windows.Point(), root);
        var progressAt = progress.TranslatePoint(new System.Windows.Point(), root);
        Require(progressAt.Y > buttonAt.Y && progressAt.Y - buttonAt.Y < 150 && progressAt.Y < 450, "advanced-progress-visible-directly-under-download-actions");
        var bitmap = new System.Windows.Media.Imaging.RenderTargetBitmap(1024, 800, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
        bitmap.Render(root);
        var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder(); encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
        using var output = File.Create(Path.Combine(Backend.Root, "logs/advanced-download-layout.png")); encoder.Save(output);
    }
    public static async Task<string> RunAsync()
    {
        var events = new List<string>(); var cases = new List<string>();
        void Require(bool condition, string name) { if (!condition) throw new IOException("CHECK FAILED: " + name); events.Add(name); }
        await using var server = new Server();
        foreach (var bad in new[] { "file:///C:/test.img", "https://user:secret@example.com/file.img", "--dir=C:/", "ftp://example.com/file.img", "https://example.com/file.img\n" })
        {
            var refused = false; try { AriaDownload.Address(bad); } catch (IOException) { refused = true; }
            Require(refused, "refuse-invalid-address");
        }
        foreach (var path in new[] { "/html.img", "/missing.img" })
        {
            var refused = false; try { await AriaDownload.CreateAsync(server.Url + path, CancellationToken.None); } catch (Exception e) when (e is IOException or System.Net.Http.HttpRequestException) { refused = true; }
            Require(refused, path + "-refused-before-task");
        }
        var job = await AriaDownload.CreateAsync(server.Url + "/image.img", CancellationToken.None); cases.Add(AriaDownload.DirectoryFor(job));
        using (var cancel = new CancellationTokenSource())
        {
            var cancelled = false;
            try { await AriaDownload.RunAsync(job, progress => { if (progress.Completed >= 2 * 1024 * 1024) cancel.Cancel(); }, cancel.Token); }
            catch (OperationCanceledException) { cancelled = true; }
            job = AriaDownload.Load(AriaDownload.DirectoryFor(job));
            Require(cancelled && job.Status == "paused" && File.Exists(Path.Combine(AriaDownload.DirectoryFor(job), "payload.part.aria2"))
                && !File.Exists(AriaDownload.ResultPath(job)), "pause-persists-aria2-control-and-no-complete-image");
        }
        var before = server.Starts.Count;
        job = await AriaDownload.RunAsync(job, _ => { }, CancellationToken.None);
        Require(job.Status == "complete" && server.Starts.Skip(before).Any(offset => offset > 0), "new-aria2-process-resumes-nonzero-range");
        Require((await File.ReadAllBytesAsync(AriaDownload.ResultPath(job))).AsSpan().SequenceEqual(server.Bytes), "resumed-download-full-ordinary-byte-equality");
        Require(!File.Exists(Path.Combine(AriaDownload.DirectoryFor(job), "operation.lock")), "download-lease-released");
        Require(AriaDownload.Find(job.RequestedUrl)?.Id == job.Id, "reopen-finds-saved-download");
        before = server.Starts.Count;
        var reused = await AriaDownload.RunAsync(job, _ => { }, CancellationToken.None);
        Require(reused.Id == job.Id && server.Starts.Count == before, "completed-local-download-reused");
        var publishing = job with { Status = "publishing" };
        var metadata = Path.Combine(AriaDownload.DirectoryFor(job), "download.json");
        File.WriteAllText(metadata, JsonSerializer.Serialize(publishing));
        job = await AriaDownload.RunAsync(publishing, _ => { }, CancellationToken.None);
        Require(job.Status == "complete" && server.Starts.Count == before, "recover-publication-after-rename-without-network");
        File.Move(AriaDownload.ResultPath(job), Path.Combine(AriaDownload.DirectoryFor(job), "payload.part"));
        File.WriteAllText(metadata, JsonSerializer.Serialize(publishing));
        job = await AriaDownload.RunAsync(publishing, _ => { }, CancellationToken.None);
        Require(job.Status == "complete" && server.Starts.Count == before
            && File.ReadAllBytes(AriaDownload.ResultPath(job)).AsSpan().SequenceEqual(server.Bytes), "recover-publication-before-rename-with-byte-equality");
        await CheckPanelAsync(server, events);
        await CheckAdvancedAsync(server, events);
        var changed = await AriaDownload.CreateAsync(server.Url + "/changed.img", CancellationToken.None); cases.Add(AriaDownload.DirectoryFor(changed));
        using (var cancel = new CancellationTokenSource())
        {
            try { await AriaDownload.RunAsync(changed, progress => { if (progress.Completed > 1024 * 1024) cancel.Cancel(); }, cancel.Token); }
            catch (OperationCanceledException) { }
        }
        var record = File.ReadAllText(Path.Combine(AriaDownload.DirectoryFor(changed), "download.json")); server.ETag = "\"fixture-v2\"";
        var rejected = false;
        try { await AriaDownload.RunAsync(changed, _ => { }, CancellationToken.None); }
        catch (IOException e) when (e.Message.Contains("Remote file changed")) { rejected = true; }
        Require(rejected && record == File.ReadAllText(Path.Combine(AriaDownload.DirectoryFor(changed), "download.json")), "changed-remote-rejected-with-original-state-preserved");
        var noRange = await AriaDownload.CreateAsync(server.Url + "/noranges.img", CancellationToken.None); cases.Add(AriaDownload.DirectoryFor(noRange));
        using (var cancel = new CancellationTokenSource())
        {
            try { await AriaDownload.RunAsync(noRange, progress => { if (progress.Completed > 1024 * 1024) cancel.Cancel(); }, cancel.Token); }
            catch (OperationCanceledException) { }
        }
        rejected = false;
        try { await AriaDownload.RunAsync(noRange, _ => { }, CancellationToken.None); }
        catch (IOException e) when (e.Message.Contains("cannot resume")) { rejected = true; }
        Require(rejected, "non-range-server-partial-not-appended");
        var report = Path.Combine(Backend.Root, "logs", "aria2-download-checks.json");
        await File.WriteAllTextAsync(report, JsonSerializer.Serialize(new { passed = true, events, cases,
            scope = "Bundled real aria2c against a bounded loopback HTTP server; pause, process restart, range resume, full byte equality, change refusal. No system image or physical disk writes." }, new JsonSerializerOptions { WriteIndented = true }));
        return report;
    }
}
