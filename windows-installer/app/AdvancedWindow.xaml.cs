using Microsoft.Win32;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.ComponentModel;
using System.Text.Json;

namespace OxpInstaller;
public partial class AdvancedWindow : Window
{
    private CancellationTokenSource? operation;
    public AdvancedWindow()
    {
        InitializeComponent(); InstallerI18n.Apply(this);
        OutputPath.Text = Path.Combine(Backend.Root, "output/oxp3-preview.img");
        var local = Path.Combine(InstallerWorkspace.DirectoryPath, "source/steamdeck-oobe-repair-20260707.10-3.8.14.img");
        if (File.Exists(local)) SourcePath.Text = local;
        WaydroidResource.IsEnabled = File.Exists(Path.Combine(Backend.Root, "cache/components/waydroid/profile.json"));
        HdrResource.IsEnabled = File.Exists(Path.Combine(Backend.Root, "cache/components/hdr/profile.json"));
        ControlResources.IsEnabled = File.Exists(Path.Combine(Backend.Root, "cache/components/oxp3-controls/profile.json"));
        Closing += OnClosing;
        InitializeDownloadSources();
    }
    private void Log(string message) => Dispatcher.Invoke(() =>
    {
        LogText.AppendText(Regex.Replace(message, @"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]", "") + (message.EndsWith('\n') ? "" : "\n"));
        if (LogText.Text.Length > 100_000) LogText.Text = LogText.Text[^70_000..];
        LogText.ScrollToEnd();
    });
    private async Task RunAsync(string title, Func<CancellationToken, Task> action, bool download = false)
    {
        var status = download ? DownloadStatus : StatusText;
        var progress = download ? DownloadProgress : Progress;
        if (operation != null) { status.Text = "当前操作尚未结束。"; return; }
        operation = new CancellationTokenSource(); CancelButton.IsEnabled = true; BuildButton.IsEnabled = false;
        SetDownloadControls(false);
        PauseDownloadButton.Visibility = download ? Visibility.Visible : Visibility.Collapsed;
        progress.Value = 0; progress.IsIndeterminate = true; status.Text = title; LogText.Clear();
        try { await action(operation.Token); status.Text = title + "完成"; }
        catch (OperationCanceledException) { status.Text = download ? "下载已暂停；再次点击下载可继续。" : "操作已取消；未完成的文件和日志保留，不能作为成品。"; }
        catch (Exception error) { status.Text = "失败：" + error.Message; Log(error.ToString()); }
        finally
        {
            operation.Dispose(); operation = null; CancelButton.IsEnabled = false; BuildButton.IsEnabled = true; progress.IsIndeterminate = false;
            PauseDownloadButton.Visibility = Visibility.Collapsed; SetDownloadControls(true);
        }
    }
    private void BrowseSource(object sender, RoutedEventArgs e)
    {
        if (operation != null) return;
        var dialog = new OpenFileDialog { Filter = "SteamOS 恢复镜像|*.img;*.img.bz2;*.img.zip" };
        if (dialog.ShowDialog() == true) SourcePath.Text = dialog.FileName;
    }
    private void BrowseOutput(object sender, RoutedEventArgs e)
    {
        if (operation != null) return;
        var dialog = new SaveFileDialog { Filter = "磁盘镜像|*.img", FileName = "oxp3-preview.img" };
        if (dialog.ShowDialog() == true) OutputPath.Text = dialog.FileName;
    }
    private async void InspectSource(object sender, RoutedEventArgs e) => await RunAsync("读取镜像信息", async token =>
    {
        var image = await Backend.ImportAsync(SourcePath.Text, Log, token);
        var result = await Backend.GuestAsync("inspect", image, false, Log, token);
        Log(result.Contains("VERSION_ID=3.8.14") ? "镜像内系统：SteamOS 3.8.14。" : "系统版本见镜像内 os-release；没有推定为设备当前系统版本。");
    });
    private async void ReadDisks(object sender, RoutedEventArgs e) => await RunAsync("读取磁盘布局", async token =>
    {
        var result = await Backend.PowerShellAsync("read-disks.ps1", [], _ => { }, token);
        DiskPreview.Text = DiskPlanning.Describe(result);
        SpaceSelector.ItemsSource = DiskPlanning.FreeSpaces(result);
        Log(SpaceSelector.Items.Count == 0 ? "未找到符合当前 GPT 标识、512 字节逻辑扇区和至少 64 GiB 空间要求的目标。仍可制作不指定磁盘的预览介质。" : "可选择已有未分配空间；将记录原分区标识，Linux 启动端会重新核对布局。");
    });
    private async void ProbeBackend(object sender, RoutedEventArgs e) => await RunAsync("验证离线后端", async token => { await Backend.GuestAsync("smoke", null, false, Log, token); });
    private async void BuildImage(object sender, RoutedEventArgs e) => await RunAsync("制作预览介质", async token =>
    {
        var source = await Backend.ImportAsync(SourcePath.Text, Log, token);
        var output = Path.GetFullPath(OutputPath.Text);
        if (!output.EndsWith(".img", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("输出扩展名必须为 .img。");
        if (File.Exists(output)) throw new InvalidOperationException("输出已存在；请选择新文件名，避免覆盖已有镜像。");
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var partial = output[..^4] + ".partial.img";
        Log("复制源镜像到独立输出文件。");
        await Backend.CopyImageAsync(source, partial, token);
        var resources = new List<string>();
        if (WaydroidResource.IsChecked == true) resources.Add("waydroid");
        if (ControlResources.IsChecked == true) resources.Add("oxp3-controls");
        if (HdrResource.IsChecked == true) resources.Add("hdr");
        var selection = JsonSerializer.Serialize(DiskPlanning.Preview(SpaceSelector.SelectedItem as SpaceChoice, resources.ToArray(), HdrComponent.IsChecked == true ? ["hdr"] : []), new JsonSerializerOptions { WriteIndented = true });
        await Backend.GuestAsync("build", partial, true, Log, token, selection);
        token.ThrowIfCancellationRequested(); File.Move(partial, output, false);
        Log("制作完成：" + output + "\n这是安装预览介质，尚未开放内置盘安装。");
    });
    private void Cancel(object sender, RoutedEventArgs e) => operation?.Cancel();
    private async void CreateVirtualDisk(object sender, RoutedEventArgs e) => await RunAsync("创建并验证虚拟测试盘", async token =>
    {
        FixturePath.Text = await Backend.CreateFixtureAsync(Log, token);
        Log("已有 EFI/NTFS 测试数据保留验证通过。这不是 Windows 启动验收。");
    });
    private async void DeployVirtualDisk(object sender, RoutedEventArgs e) => await RunAsync("验证虚拟盘系统部署", async token =>
    {
        Backend.VerifyFixture(FixturePath.Text);
        var source = await Backend.ImportAsync(SourcePath.Text, Log, token);
        await Backend.GuestAsync("deployment-test", source, false, Log, token, fixture: FixturePath.Text);
        Log("SteamOS A/B 根系统与独立引导配置生成通过；启动验收另行执行。");
    });
    private void BrowseFixture(object sender, RoutedEventArgs e)
    {
        if (operation != null) return;
        var dialog = new OpenFileDialog { Filter = "本工具创建的虚拟测试盘|windows-fixture.qcow2", InitialDirectory = InstallerWorkspace.DirectoryPath };
        if (dialog.ShowDialog() != true) return;
        try { Backend.VerifyFixture(dialog.FileName); FixturePath.Text = dialog.FileName; }
        catch (Exception error) { StatusText.Text = error.Message; }
    }
    private async void BootVirtualDisk(object sender, RoutedEventArgs e) => await RunAsync("验证虚拟盘 UEFI 启动", async token =>
    {
        await VirtualBoot.RunAsync(FixturePath.Text, Log, token);
    });
    private async void TestVirtualPlugins(object sender, RoutedEventArgs e) => await RunAsync("验证虚拟盘插件部署与恢复", async token =>
    {
        Backend.VerifyFixture(FixturePath.Text);
        var source = await Backend.ImportAsync(SourcePath.Text, Log, token);
        await Backend.GuestAsync("plugin-test", source, false, Log, token, fixture: FixturePath.Text);
        Log("后端加载、前端文件提供和独立恢复检查通过；尚未验证 Steam 前端注入或在线功能。");
    });
    private async void TestMediaInstall(object sender, RoutedEventArgs e) => await RunAsync("验证制作介质的虚拟安装流程", async token =>
    {
        var directory = await Backend.CheckHandoffAsync(Log, token, OutputPath.Text);
        FixturePath.Text = Path.Combine(directory, "windows-fixture.qcow2");
        Log("Windows 规划到 Linux 确认及安装核心、A/B 部署、重试、预览层移除和资源携带检查通过。UEFI 启动可继续单独验证；测试盘没有 Windows 操作系统。");
    });
    private async void BootPreviewImage(object sender, RoutedEventArgs e) => await RunAsync("验证预览镜像 UEFI 启动", async token =>
    {
        await VirtualBoot.PreviewAsync(OutputPath.Text, Log, token);
    });
    private async void TestWindowsMediaWrite(object sender, RoutedEventArgs e) => await RunAsync("验证 Windows 介质写入", async token =>
    {
        var operation = await MediaWriterController.RunVirtualAsync(OutputPath.Text, progress =>
        {
            Progress.IsIndeterminate = false;
            Progress.Value = progress.Total > 0 ? 100d * (progress.Written + progress.Verified) / (2 * progress.Total) : 0;
            var done = progress.Stage == "verifying" ? progress.Verified : progress.Written;
            StatusText.Text = progress.Stage switch
            {
                "validating" => "核对源镜像…",
                "checking-space" => "检查工作目录可用空间…",
                "complete" => "写入与整份读回完成，虚拟介质已卸载。",
                "cancelled" => "写入已取消，正在核对清理结果…",
                "failed" => "介质操作失败，正在核对清理结果…",
                _ => (progress.Stage == "verifying" ? "读回介质" : "写入介质") + $"：{done / 1048576d:F0} MiB / {progress.Total / 1048576d:F0} MiB"
            };
        }, token);
        Log("介质操作记录：" + operation.Directory + "；写入 " + operation.Result.Written + " 字节，已读回 " + operation.Result.Verified + " 字节；清理已确认：" + operation.Result.Detached);
        if (operation.Result.Status == "cancelled") throw new OperationCanceledException(token);
        if (operation.Result.Status != "complete") throw new IOException(operation.Result.Error);
        Log("Windows 虚拟介质整份写入和读回核对通过：" + operation.Directory + "。物理 U 盘验收与 UEFI 启动另行执行。");
    });
    private async void ReadUsbMedia(object sender, RoutedEventArgs e) => await RunAsync("读取 U 盘候选", async token =>
    {
        UsbMediaSelector.ItemsSource = null;
        var source = MediaSource.Read(OutputPath.Text); var inventory = await UsbMediaPlanning.ReadAsync(source.Path, token);
        var choices = UsbMediaPlanning.Choices(inventory, source.Length); UsbMediaSelector.ItemsSource = choices;
        UsbMediaPreview.Text = choices.Length == 0 ? "没有发现 USB 候选设备。" : "选择设备后重新核对；当前不写入磁盘。";
        Log("只读查询完成：" + choices.Length + " 个 USB 候选，" + choices.Count(c => c.Eligible) + " 个可核对。");
    });
    private async void RecheckUsbMedia(object sender, RoutedEventArgs e) => await RunAsync("重新核对 U 盘", async token =>
    {
        if (UsbMediaSelector.SelectedItem is not UsbChoice choice || !choice.Eligible) throw new IOException("请选择可核对的设备。");
        var source = MediaSource.Read(OutputPath.Text); var fresh = await UsbMediaPlanning.ReadAsync(source.Path, token);
        var disk = UsbMediaPlanning.Rebind(choice.Disk, fresh, source.Length);
        Log("将启动独立管理员进程，只读取所选设备与源卷的原生元数据。" );
        var native = await UsbNativeReview.RunAsync(source.Path, disk, token);
        Log("原生只读核对记录：" + native.Directory);
        if (native.Result.Status != "checked-readonly") throw new IOException(native.Result.Error);
        Log("原生设备句柄、源卷排除与完整目标卷集合核对通过：" + native.Result.TargetVolumes!.Length + " 个卷。" );
        UsbMediaPreview.Text = $"磁盘 {disk.Number} · {disk.Model}\n序列号：{disk.Serial}\n容量：{disk.Size / 1073741824d:F2} GiB；镜像：{source.Length / 1073741824d:F2} GiB\n现有分区：{disk.Partitions.Length}。后续整盘写入将覆盖现有分区；本次只核对，没有写入。";
        Log("设备身份、容量、分区及源盘排除重新核对通过。物理写入门禁保持关闭。");
    });
    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (operation != null) { e.Cancel = true; operation.Cancel(); StatusText.Text = "正在取消；操作结束后可关闭。"; }
    }
}

