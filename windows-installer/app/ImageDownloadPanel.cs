using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public sealed class ImageDownloadPanel : UserControl
{
    private readonly ComboBox sources = new() { MinHeight = 48, Margin = new(0, 8, 0, 8) };
    private readonly TextBox address = new() { MinHeight = 48, TextWrapping = TextWrapping.Wrap, Margin = new(0, 0, 0, 8) };
    private readonly TextBlock heading = new() { FontSize = 19, FontWeight = FontWeights.SemiBold };
    private readonly TextBlock note = new() { TextWrapping = TextWrapping.Wrap, Margin = new(0, 0, 0, 12), Foreground = Brushes.SlateGray };
    private readonly CheckBox agreement = new() { Margin = new(0, 4, 0, 8) };
    private readonly Button terms = new() { HorizontalAlignment = HorizontalAlignment.Left, Margin = new(8, 0, 0, 0) };
    private readonly Button action = new() { MinWidth = 120, Margin = new(0, 0, 10, 0) };
    private readonly Button restart = new() { Margin = new(0) };
    private readonly Button copyAddress = new() { Margin = new(8, 0, 0, 8), VerticalAlignment = VerticalAlignment.Top };
    private readonly TextBlock status = new() { TextWrapping = TextWrapping.Wrap, Margin = new(0, 10, 0, 0) };
    private readonly ProgressBar progress = new() { Height = 7, Margin = new(0, 12, 0, 0), Visibility = Visibility.Collapsed };
    private readonly DownloadOrigin[] origins = AriaDownload.Origins();
    private CancellationTokenSource? operation;
    public bool IsBusy => operation != null;
    public void RefreshWorkspace() { if (!IsBusy) { status.Text = ""; progress.Value = 0; Choose(); } }
    public event Action<bool>? BusyChanged;
    public event Action<string>? Completed;
    private static string L(string zh, string en) => InstallerI18n.Language == "en-US" ? en : zh;
    public ImageDownloadPanel()
    {
        var body = new StackPanel();
        var statusStyle = new Style(typeof(TextBlock));
        var emptyStatus = new Trigger { Property = TextBlock.TextProperty, Value = "" };
        emptyStatus.Setters.Add(new Setter(VisibilityProperty, Visibility.Collapsed));
        statusStyle.Triggers.Add(emptyStatus); status.Style = statusStyle;
        body.Children.Add(heading); body.Children.Add(sources);
        var addressRow = new DockPanel();
        DockPanel.SetDock(copyAddress, Dock.Right); addressRow.Children.Add(copyAddress); addressRow.Children.Add(address);
        body.Children.Add(addressRow); body.Children.Add(note);
        var consent = new WrapPanel(); consent.Children.Add(agreement); consent.Children.Add(terms); body.Children.Add(consent);
        var buttons = new WrapPanel(); buttons.Children.Add(action); buttons.Children.Add(restart); body.Children.Add(buttons);
        body.Children.Add(progress); body.Children.Add(status); Content = body;
        sources.SelectionChanged += (_, _) => Choose();
        action.Click += async (_, _) => { if (IsBusy) Pause(); else await DownloadAsync(false); };
        restart.Click += async (_, _) => { if (!IsBusy) await DownloadAsync(true); };
        copyAddress.Click += (_, _) =>
        {
            try
            {
                var url = address.Text.Trim();
                AriaDownload.Address(url);
                Clipboard.SetText(url);
                if (!IsBusy) status.Text = L("下载地址已复制。可粘贴到浏览器或下载工具；下载完成后，在下方选择本地恢复镜像。",
                    "Download URL copied. Paste it into your browser or download manager, then select the local recovery image below.");
            }
            catch (Exception error) { if (!IsBusy) status.Text = error.Message; }
        };
        address.TextChanged += (_, _) => copyAddress.IsEnabled = !string.IsNullOrWhiteSpace(address.Text);
        terms.Click += (_, _) => {
            try { Process.Start(new ProcessStartInfo("https://store.steampowered.com/steamos/download/?ver=steamdeck") { UseShellExecute = true }); }
            catch (Exception error) { status.Text = error.Message; }
        };
        RefreshLanguage();
    }
    public void RefreshLanguage()
    {
        var index = Math.Max(0, sources.SelectedIndex); var custom = address.Text;
        heading.Text = L("下载恢复镜像", "Download a recovery image");
        agreement.Content = L("我已阅读并同意 SteamOS 下载条款", "I have read and accept the SteamOS download terms");
        terms.Content = L("查看 Valve 下载条款 ↗", "View Valve download terms ↗");
        copyAddress.Content = L("复制地址 · 手动下载", "Copy URL · download manually");
        copyAddress.ToolTip = L("复制当前下载地址，使用浏览器或下载工具手动下载", "Copy the current URL to download with your browser or download manager");
        sources.Items.Clear();
        foreach (var origin in origins) sources.Items.Add(origin);
        sources.Items.Add(L("自定义镜像直链", "Custom mirror URL"));
        sources.SelectedIndex = Math.Min(index, origins.Length);
        if (index == origins.Length) address.Text = custom;
        action.Content = IsBusy ? L("暂停下载", "Pause") : L("下载 / 继续", "Download / resume");
        restart.Content = L("重新下载", "Start fresh");
    }
    private void Choose()
    {
        var index = sources.SelectedIndex;
        if (index < 0) return;
        var custom = index >= origins.Length;
        address.IsReadOnly = !custom;
        address.Text = custom ? "" : origins[index].Url;
        note.Text = custom ? L("填写 .img、.img.bz2 或 .img.zip 的 HTTPS 直链。更换来源会使用新的下载记录。",
            "Enter a direct HTTPS .img, .img.bz2 or .img.zip URL. Each source keeps separate download progress.")
            : InstallerI18n.Language == "en-US" ? origins[index].EnglishNote : origins[index].Note;
        progress.Value = 0; progress.Visibility = Visibility.Collapsed; status.Text = "";
    }
    public void Pause() { operation?.Cancel(); action.IsEnabled = false; status.Text = L("正在保存下载进度…", "Saving download progress…"); }
    internal async Task DownloadAsync(bool fresh)
    {
        if (operation != null) return;
        if (agreement.IsChecked != true) { status.Text = L("请先阅读并接受下载条款。", "Read and accept the download terms first."); return; }
        var url = address.Text.Trim();
        try { AriaDownload.Address(url); }
        catch (Exception error) { status.Text = error.Message; return; }
        operation = new CancellationTokenSource(); sources.IsEnabled = address.IsEnabled = restart.IsEnabled = agreement.IsEnabled = false;
        action.Content = L("暂停下载", "Pause"); progress.Visibility = Visibility.Visible; progress.IsIndeterminate = true;
        BusyChanged?.Invoke(true);
        try
        {
            status.Text = L("正在检查下载来源…", "Checking the download source…");
            var job = fresh ? null : AriaDownload.Find(url);
            job ??= await AriaDownload.CreateAsync(url, operation.Token);
            var result = await AriaDownload.RunAsync(job, p => Dispatcher.Invoke(() =>
            {
                progress.IsIndeterminate = false; progress.Value = p.Total > 0 ? p.Completed * 100d / p.Total : 0;
                var eta = p.Speed > 0 ? TimeSpan.FromSeconds(Math.Max(0, p.Total - p.Completed) / p.Speed).ToString(@"hh\:mm\:ss") : "--:--:--";
                status.Text = $"{p.Completed / 1048576d:F1} / {p.Total / 1048576d:F1} MiB  ·  {p.Speed / 1048576d:F1} MiB/s  ·  " + L("剩余 ", "Remaining ") + eta;
            }), operation.Token);
            Completed?.Invoke(AriaDownload.ResultPath(result));
            status.Text = L("下载完成，已选为下方的系统镜像。可以继续下一步。", "Downloaded and selected below. Continue to the next step.");
        }
        catch (OperationCanceledException) { status.Text = L("下载已暂停。再次点击“下载 / 继续”可续传。", "Paused. Click Download / resume to continue."); }
        catch (Exception error) { status.Text = error.Message; }
        finally
        {
            operation.Dispose(); operation = null; progress.IsIndeterminate = false;
            sources.IsEnabled = address.IsEnabled = restart.IsEnabled = agreement.IsEnabled = action.IsEnabled = true;
            action.Content = L("下载 / 继续", "Download / resume"); BusyChanged?.Invoke(false);
        }
    }
}
