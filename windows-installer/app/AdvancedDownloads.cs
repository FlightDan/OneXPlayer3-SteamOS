using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;

namespace OxpInstaller;

public partial class AdvancedWindow
{
    private CancellationTokenSource? sourceProbe;
    private int sourceSelectionRevision;
    private static string DownloadLabel(string zh, string en) => InstallerI18n.Language == "en-US" ? en : zh;

    private void InitializeDownloadSources()
    {
        CopyDownloadAddressButton.Content = DownloadLabel("复制下载地址（自行下载）", "Copy link (download yourself)");
        foreach (var origin in AriaDownload.Origins().Where(o => o.Version == "3.8.14"))
            DownloadSourceSelector.Items.Add(new ComboBoxItem { Content = origin.ToString(), Tag = origin });
        DownloadSourceSelector.Items.Add(new ComboBoxItem { Content = DownloadLabel("自定义镜像源（HTTPS 直链）", "Custom mirror (HTTPS URL)") });
        DownloadSourceSelector.SelectedIndex = 0;
        Loaded += async (_, _) => await ProbeDownloadSourcesAsync();
        Closed += (_, _) => sourceProbe?.Cancel();
    }

    private void SetDownloadControls(bool enabled)
    {
        DownloadButton.IsEnabled = enabled && sourceProbe == null;
        RestartDownloadButton.IsEnabled = enabled && sourceProbe == null;
        CheckSourcesButton.IsEnabled = enabled && sourceProbe == null;
        DownloadSourceSelector.IsEnabled = CustomDownloadUrl.IsEnabled = enabled;
    }

    private void DownloadSourceChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CustomDownloadUrl == null) return;
        sourceSelectionRevision++;
        var custom = (DownloadSourceSelector.SelectedItem as ComboBoxItem)?.Tag is not DownloadOrigin;
        CustomDownloadUrl.Visibility = custom ? Visibility.Visible : Visibility.Collapsed;
        DownloadButton.Content = custom ? DownloadLabel("下载 / 继续", "Download / resume") : InstallerI18n.T("下载官方 3.8.14");
        DownloadSourceStatus.Text = custom
            ? DownloadLabel("填写 HTTPS 镜像直链，可点击“重新检测”检查可用性。", "Enter a direct HTTPS image URL; click Check again to test it.")
            : DownloadLabel("打开后自动检测；也可点击“重新检测”更新各入口状态。", "Links are checked on opening; click Check again to refresh their status.");
    }

    private async void CheckDownloadSources(object sender, RoutedEventArgs e) => await ProbeDownloadSourcesAsync();

    internal async Task ProbeDownloadSourcesAsync()
    {
        if (sourceProbe != null || operation != null) return;
        using var cancellation = new CancellationTokenSource(); sourceProbe = cancellation;
        SetDownloadControls(true);
        var revision = sourceSelectionRevision;
        var customSelected = (DownloadSourceSelector.SelectedItem as ComboBoxItem)?.Tag is not DownloadOrigin;
        var customUrl = CustomDownloadUrl.Text.Trim();
        DownloadSourceStatus.Text = DownloadLabel("正在检测镜像链接可用性…", "Checking image links…");
        try
        {
            if (customSelected)
            {
                var result = await DownloadSourceProbe.CheckAsync(customUrl, cancellation.Token);
                if (revision == sourceSelectionRevision && CustomDownloadUrl.Text.Trim() == customUrl)
                    DownloadSourceStatus.Text = result.Available
                        ? DownloadLabel($"自定义源可用 · {result.Milliseconds} ms", $"Custom mirror available · {result.Milliseconds} ms")
                        : DownloadLabel("自定义源不可用：", "Custom mirror unavailable: ") + result.Error;
                return;
            }
            var items = DownloadSourceSelector.Items.OfType<ComboBoxItem>().Where(i => i.Tag is DownloadOrigin).ToArray();
            var results = await Task.WhenAll(items.Select(async item =>
            {
                var origin = (DownloadOrigin)item.Tag;
                var result = await DownloadSourceProbe.CheckAsync(origin.Url, cancellation.Token);
                item.Content = origin + (result.Available
                    ? DownloadLabel($" · 可用 {result.Milliseconds} ms", $" · Available {result.Milliseconds} ms")
                    : DownloadLabel(" · 不可用", " · Unavailable"));
                item.ToolTip = result.Error ?? origin.Url;
                return (Item: item, Result: result);
            }));
            var best = results.Where(r => r.Result.Available)
                .OrderBy(r => ((DownloadOrigin)r.Item.Tag).Url.EndsWith(".img.zip", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
                .ThenBy(r => r.Result.Milliseconds).FirstOrDefault();
            if (revision != sourceSelectionRevision)
            {
                DownloadSourceStatus.Text = DownloadLabel("检测完成，已保留手动选择；各入口状态见下拉列表。", "Checks complete; your selection was kept. See the list for link status.");
                return;
            }
            if (best.Item != null)
            {
                DownloadSourceSelector.SelectedItem = best.Item;
                DownloadSourceStatus.Text = DownloadLabel("已优先选择可用的官方 ZIP 镜像；ZIP 不可用时使用其他入口。也可手动选择 BZ2 或自定义源。",
                    "An available official ZIP image is preferred; other links are used if ZIP is unavailable. You can also select BZ2 or a custom mirror.");
            }
            else DownloadSourceStatus.Text = DownloadLabel("预置源暂时均不可用；可重新检测或选择自定义镜像源。", "No preset source is available. Retry or select a custom mirror.");
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        catch (Exception error) { DownloadSourceStatus.Text = DownloadLabel("检测失败：", "Check failed: ") + error.Message; }
        finally { sourceProbe = null; SetDownloadControls(operation == null); }
    }

    private async void DownloadSource(object sender, RoutedEventArgs e) => await DownloadRecoveryAsync();
    private async void RestartDownload(object sender, RoutedEventArgs e) => await DownloadRecoveryAsync(fresh: true);

    private void CopyDownloadAddress(object sender, RoutedEventArgs e) => CopyDownloadAddressTo(Clipboard.SetText);

    internal void CopyDownloadAddressTo(Action<string> copy)
    {
        try
        {
            var origin = (DownloadSourceSelector.SelectedItem as ComboBoxItem)?.Tag as DownloadOrigin;
            var url = AriaDownload.Address(origin?.Url ?? CustomDownloadUrl.Text.Trim());
            if (!new[] { ".img", ".img.bz2", ".img.zip" }.Any(suffix => url.AbsolutePath.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)))
                throw new System.IO.IOException(DownloadLabel("请填写 .img、.img.bz2 或 .img.zip 的 HTTPS 镜像直链。", "Enter a direct HTTPS .img, .img.bz2 or .img.zip URL."));
            copy(url.AbsoluteUri);
            DownloadSourceStatus.Text = DownloadLabel("下载地址已复制。可粘贴到浏览器或下载器，下载后点击“选择文件”。",
                "Link copied. Paste it into your browser or downloader, then use Choose file after downloading.");
        }
        catch (Exception error) { DownloadSourceStatus.Text = DownloadLabel("复制失败：", "Could not copy: ") + error.Message; }
    }

    internal async Task DownloadRecoveryAsync(bool fresh = false)
    {
        if (sourceProbe != null) return;
        var origin = (DownloadSourceSelector.SelectedItem as ComboBoxItem)?.Tag as DownloadOrigin;
        var url = origin?.Url ?? CustomDownloadUrl.Text.Trim();
        await RunAsync(DownloadLabel("下载恢复镜像", "Download recovery image"), async token =>
        {
            AriaDownload.Address(url);
            var job = fresh ? null : AriaDownload.Find(url);
            job ??= await AriaDownload.CreateAsync(url, token);
            var result = await AriaDownload.RunAsync(job, p => Dispatcher.Invoke(() =>
            {
                DownloadProgress.IsIndeterminate = p.Total <= 0;
                DownloadProgress.Value = p.Total > 0 ? p.Completed * 100d / p.Total : 0;
                var eta = p.Speed > 0 ? TimeSpan.FromSeconds(Math.Max(0, p.Total - p.Completed) / p.Speed).ToString(@"hh\:mm\:ss") : "--:--:--";
                DownloadStatus.Text = $"{DownloadProgress.Value:F1}% · {p.Completed / 1048576d:F1} / {p.Total / 1048576d:F1} MiB · {p.Speed / 1048576d:F1} MiB/s · "
                    + DownloadLabel("剩余 ", "Remaining ") + eta;
            }), token);
            SourcePath.Text = AriaDownload.ResultPath(result);
            Log(DownloadLabel("下载完成，已选择此恢复镜像。", "Download complete; recovery image selected."));
        }, download: true);
        RestartDownloadButton.Visibility = Visibility.Visible;
    }
}

internal sealed record DownloadSourceProbe(bool Available, long Milliseconds, string? Error)
{
    internal static async Task<DownloadSourceProbe> CheckAsync(string url, CancellationToken token)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(8));
        var watch = Stopwatch.StartNew();
        try
        {
            // Range GET checks the actual image endpoint, including redirects and HTTP failures.
            await AriaDownload.ProbeAsync(url, timeout.Token);
            return new(true, watch.ElapsedMilliseconds, null);
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested)
        { return new(false, watch.ElapsedMilliseconds, "连接超时 / Connection timed out"); }
        catch (Exception error) when (error is not OperationCanceledException)
        { return new(false, watch.ElapsedMilliseconds, error.Message); }
    }
}
