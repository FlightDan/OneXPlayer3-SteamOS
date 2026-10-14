using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Win32;
using System.Diagnostics;

namespace OxpInstaller;

public sealed class OfficialDownloadPanel : UserControl
{
    private readonly TextBlock heading = new() { FontSize = 19, FontWeight = FontWeights.SemiBold };
    private readonly ComboBox sources = new() { MinHeight = 48, Margin = new(0, 8, 0, 8) };
    private readonly TextBox address = new() { IsReadOnly = true, MinHeight = 48, TextWrapping = TextWrapping.Wrap, Margin = new(0, 0, 0, 8), Text = OfficialSystem.BaseUrl + ".raucb" };
    private readonly Button copyAddress = new() { Margin = new(8, 0, 0, 8), VerticalAlignment = VerticalAlignment.Top };
    private readonly CheckBox agreement = new() { Margin = new(0, 4, 0, 8) };
    private readonly Button terms = new() { HorizontalAlignment = HorizontalAlignment.Left, Margin = new(8, 0, 0, 0) };
    private readonly Button restart = new() { Margin = new(0) };
    private readonly TextBlock localHeading = new() { FontSize = 19, FontWeight = FontWeights.SemiBold, Margin = new(0, 0, 0, 10) };
    private readonly TextBlock localNote = new() { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray, LineHeight = 23 };
    private readonly TextBlock localHint = new() { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray, FontSize = 12, LineHeight = 23 };
    private readonly TextBox localPath = new() { IsReadOnly = true, VerticalContentAlignment = VerticalAlignment.Center };
    private readonly TextBlock localStatus = new() { TextWrapping = TextWrapping.Wrap, Margin = new(0, 10, 0, 0), Visibility = Visibility.Collapsed };
    private readonly Button browse = new() { Margin = new(10, 0, 0, 0) };
    private readonly TextBlock note = new() { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SlateGray, Margin = new(0, 4, 0, 10) };
    private readonly Button action = new() { HorizontalAlignment = HorizontalAlignment.Left, MinHeight = 48 };
    private readonly TextBlock status = new() { TextWrapping = TextWrapping.Wrap, Margin = new(0, 10, 0, 0) };
    private readonly ProgressBar progress = new() { Height = 7, Margin = new(0, 12, 0, 0), Visibility = Visibility.Collapsed };
    private CancellationTokenSource? operation;
    private bool required = true;
    public bool IsBusy => operation != null;
    public event Action<bool>? BusyChanged;
    private static string L(string zh, string en) => PartitionInventory.L(zh, en);
    private static Border Card(UIElement content) => new()
    {
        Child = content, Background = Brushes.White, CornerRadius = new(12), Padding = new(16), Margin = new(0, 0, 0, 12),
        BorderBrush = new SolidColorBrush(Color.FromRgb(223, 230, 240)), BorderThickness = new(1)
    };
    public OfficialDownloadPanel()
    {
        var statusStyle = new Style(typeof(TextBlock));
        var emptyStatus = new Trigger { Property = TextBlock.TextProperty, Value = "" };
        emptyStatus.Setters.Add(new Setter(VisibilityProperty, Visibility.Collapsed));
        statusStyle.Triggers.Add(emptyStatus); status.Style = statusStyle;
        var body = new StackPanel(); var download = new StackPanel();
        download.Children.Add(heading); download.Children.Add(sources);
        var addressRow = new DockPanel(); DockPanel.SetDock(copyAddress, Dock.Right);
        addressRow.Children.Add(copyAddress); addressRow.Children.Add(address); download.Children.Add(addressRow); download.Children.Add(note);
        var consent = new WrapPanel(); consent.Children.Add(agreement); consent.Children.Add(terms); download.Children.Add(consent);
        var buttons = new WrapPanel(); action.Margin = new(0, 0, 10, 0); buttons.Children.Add(action); buttons.Children.Add(restart); download.Children.Add(buttons);
        download.Children.Add(progress); download.Children.Add(status); body.Children.Add(Card(download));
        var local = new StackPanel(); local.Children.Add(localHeading); local.Children.Add(localNote);
        var localRow = new DockPanel { Margin = new(0, 8, 0, 8) }; DockPanel.SetDock(browse, Dock.Right);
        localRow.Children.Add(browse); localRow.Children.Add(localPath); local.Children.Add(localRow); local.Children.Add(localHint);
        local.Children.Add(localStatus);
        body.Children.Add(Card(local)); Content = body;
        action.Click += async (_, _) => { if (IsBusy) Pause(); else await DownloadAsync(); };
        restart.Click += async (_, _) => { if (!IsBusy) await DownloadAsync(fresh: true); };
        browse.Click += async (_, _) =>
        {
            var dialog = new OpenFileDialog { Filter = L("SteamOS 3.10 系统镜像|*.img;*.raucb", "SteamOS 3.10 system image|*.img;*.raucb") };
            if (dialog.ShowDialog(Window.GetWindow(this)) == true) await DownloadAsync(dialog.FileName);
        };
        copyAddress.Click += (_, _) =>
        {
            try { Clipboard.SetText(address.Text); if (!IsBusy) SetStatus(L("地址已复制。下载后，在下方选择本地更新包即可继续。", "URL copied. Select the downloaded bundle below to continue.")); }
            catch (Exception error) { if (!IsBusy) SetStatus(error.Message); }
        };
        terms.Click += (_, _) =>
        {
            try { Process.Start(new ProcessStartInfo("https://store.steampowered.com/steamos/download/?ver=steamdeck") { UseShellExecute = true }); }
            catch (Exception error) { if (!IsBusy) SetStatus(error.Message); }
        };
        RefreshLanguage();
    }
    public void SetRequired(bool value)
    {
        var changed = required != value;
        required = value;
        if (!IsBusy) { SetControls(); if (changed) RefreshStatus(); }
    }
    private void SetControls()
    {
        action.IsEnabled = required;
        browse.IsEnabled = restart.IsEnabled = agreement.IsEnabled = required && !IsBusy;
        sources.IsEnabled = !IsBusy;
    }
    public void RefreshWorkspace() { if (!IsBusy) { localPath.Text = ""; localStatus.Visibility = Visibility.Collapsed; progress.Visibility = Visibility.Collapsed; RefreshStatus(); } }
    public void RefreshLanguage()
    {
        heading.Text = L("下载 3.10 镜像", "Download the 3.10 image");
        sources.Items.Clear(); sources.Items.Add(L("Valve 官方系统镜像 · 3.10 · build 20260924.1000（推荐）", "Valve system image · 3.10 · build 20260924.1000 (Recommended)")); sources.SelectedIndex = 0;
        copyAddress.Content = L("复制地址 · 手动下载", "Copy URL · download manually");
        note.Text = L("下载 .raucb 更新包后即可继续。开始安装后，再联网获取系统数据并重建镜像。", "Download the .raucb update bundle to continue. System data is downloaded and the image rebuilt after installation starts.");
        agreement.Content = L("我已阅读并同意 SteamOS 下载条款", "I have read and accept the SteamOS download terms");
        terms.Content = L("查看 Valve 下载条款 ↗", "View Valve download terms ↗");
        restart.Content = L("重新下载", "Start fresh");
        localHeading.Text = L("选择本地 3.10 镜像", "Select a local 3.10 image");
        localNote.Text = L("使用本地 SteamOS 3.10 系统镜像；导入后，安装时使用工作空间中的副本。", "Import a local SteamOS 3.10 system image for installation from your workspace.");
        browse.Content = L("选择文件…", "Choose file…");
        localHint.Text = L("支持 .raucb 更新包或已重建的 rootfs.img。请选择 build 20260924.1000；更新包会在开始安装后联网重建。", "Accepts a .raucb bundle or a rebuilt rootfs.img. Select build 20260924.1000; bundles are rebuilt online after installation starts.");
        System.Windows.Automation.AutomationProperties.SetName(localPath, L("3.10 镜像路径", "3.10 image path"));
        System.Windows.Automation.AutomationProperties.SetName(sources, heading.Text);
        RefreshStatus();
    }
    private void SetStatus(string message) { status.Text = localStatus.Text = message; }
    private void RefreshStatus()
    {
        if (IsBusy) return;
        var cached = OfficialSystem.HasPreparedSource();
        localPath.Text = cached ? OfficialSystem.RequirePreparedSource() : "";
        action.Content = L("下载 / 继续", "Download / resume");
        SetControls();
        SetStatus(cached ? ""
            : required ? L("尚未准备。请下载镜像或选择本地文件。", "Not ready. Download the image or select a local file.")
            : L("当前方案无需下载官方 3.10。", "This configuration does not need the official 3.10 download."));
    }
    public void Pause()
    {
        operation?.Cancel(); action.IsEnabled = false;
        SetStatus(L("正在停止下载并保留已有系统数据…", "Stopping the download and retaining existing system data…"));
    }
    internal async Task DownloadAsync(string? local = null, bool fresh = false)
    {
        if (IsBusy || !required) return;
        var importing = local != null && local.EndsWith(".img", StringComparison.OrdinalIgnoreCase);
        localStatus.Visibility = local != null ? Visibility.Visible : Visibility.Collapsed;
        if (local == null && agreement.IsChecked != true) { SetStatus(L("请先阅读并接受下载条款。", "Read and accept the download terms first.")); return; }
        operation = new CancellationTokenSource();
        if (local != null)
        {
            localPath.Text = local;
            SetStatus(L("正在导入本地文件：", "Importing local file: ") + Path.GetFileName(local));
        }
        SetControls(); action.Content = L("暂停", "Pause");
        progress.Value = 0; progress.Visibility = Visibility.Visible; progress.IsIndeterminate = true;
        BusyChanged?.Invoke(true);
        var logPath = Path.Combine(InstallerWorkspace.DirectoryPath, "official-3.10-download.log");
        try
        {
            Directory.CreateDirectory(InstallerWorkspace.DirectoryPath);
            MediaSource.Ordinary(logPath, InstallationController.Work, false);
            using var log = new StreamWriter(new FileStream(logPath, FileMode.Append, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
            void Report(OfficialPreparationProgress update) => Dispatcher.Invoke(() =>
            {
                progress.IsIndeterminate = update.Step == "01.02.02" || update.Fraction == 0;
                progress.Value = Math.Max(progress.Value, update.Fraction * 100);
                SetStatus(update.Message);
                System.Windows.Automation.AutomationProperties.SetName(progress, update.Message);
            });
            localPath.Text = importing
                ? await OfficialSystem.ImportRootAsync(local!, operation.Token, Report)
                : await OfficialSystem.StageBundleAsync(line => { lock (log) log.WriteLine(line); }, operation.Token, Report, local, fresh);
            progress.IsIndeterminate = false; progress.Value = 100;
            SetStatus(L("文件已就绪，可以点击“下一步”。", "File ready. Click Next to continue."));
        }
        catch (OperationCanceledException)
        {
            SetStatus(L("准备已暂停。再次点击可继续；已有系统数据块会重新检查并复用。", "Preparation paused. Click again to continue; existing system chunks will be checked and reused."));
        }
        catch (Exception error) { SetStatus(L("准备未完成：", "Preparation incomplete: ") + error.Message); }
        finally
        {
            operation.Dispose(); operation = null; progress.IsIndeterminate = false;
            localPath.Text = OfficialSystem.HasPreparedSource() ? OfficialSystem.RequirePreparedSource() : "";
            action.Content = L("下载 / 继续", "Download / resume");
            SetControls();
            BusyChanged?.Invoke(false);
            if (local != null) localStatus.BringIntoView();
        }
    }
}
