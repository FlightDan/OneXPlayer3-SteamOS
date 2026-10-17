using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public partial class MainWindow
{
    private readonly bool[] departedSteps = new bool[8];
    private bool reviewSeen;
    private bool contentSeen;
    private bool checkedAllSteps;

    private void NavigateStep(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string tag } && int.TryParse(tag, out var destination) && destination is >= 0 and <= StorageStep)
        {
            if (destination == 1) sourceSection = 0;
            ShowStep(destination);
        }
    }

    private void ConfigurationChanged()
    {
        if (!ready) return;
        PhysicalConsent.IsChecked = false;
        reviewSeen = false;
        UpdateNavigationState();
    }

    // Navigation checks are read-only. Execution still performs the controller's full validation.
    private string? TargetIssue()
    {
        if (Kind != InstallationTargetKind.InternalShared && !physicalInstallation) return null;
        try
        {
            var selection = PartitionSelector.Selection;
            if (physicalInstallation && selection.Example)
                return PartitionInventory.L("请选择真实磁盘的未分配空间。", "Select unallocated space on a real disk.");
            return null;
        }
        catch (Exception error) when (error is InvalidOperationException or IOException or ArgumentException)
        { return error.Message; }
    }

    private string? SourceIssue(bool includeOfficial = true)
    {
        if (DownloadsBusy) return PartitionInventory.L("系统镜像仍在下载。", "The system image is still downloading.");
        try
        {
            if (!File.Exists(ImagePath.Text)) return PartitionInventory.L("请选择存在的系统镜像。", "Select an existing system image.");
            if (UsePrepared.IsChecked == true)
            {
                using var image = new PreparedDiskImage(ImagePath.Text);
                if (image.Layout.Size != InstallationController.Capacity)
                    return PartitionInventory.L("请选择本工具生成的 80 GiB 预部署镜像。", "Select an 80 GiB image prepared by this tool.");
            }
            else if (!new[] { ".img", ".img.bz2", ".img.zip" }.Any(extension => ImagePath.Text.EndsWith(extension, StringComparison.OrdinalIgnoreCase)))
                return PartitionInventory.L("请选择 .img、.img.bz2 或 .img.zip 镜像。", "Select an .img, .img.bz2 or .img.zip image.");
            if (includeOfficial && UsePrepared.IsChecked != true && Upgrade310.IsChecked == true) OfficialSystem.RequirePreparedSource();
            return null;
        }
        catch (Exception error) when (error is IOException or InvalidOperationException or ArgumentException or UnauthorizedAccessException)
        { return error.Message; }
    }

    private string? ContentIssue()
    {
        try { InstallerOptions.Validate(CurrentOptions); return null; }
        catch (Exception error) when (error is IOException or InvalidOperationException or ArgumentException)
        { return error.Message; }
    }

    private string SystemVersionSummary() => UsePrepared.IsChecked == true
        ? PartitionInventory.L("安装版本：沿用已准备镜像中的系统，不再替换版本。", "Installed version: keep the system in the prepared image.")
        : Upgrade310.IsChecked == true
            ? PartitionInventory.L("安装版本：", "Installed version: ") + $"SteamOS {OfficialSystem.Version} · build {OfficialSystem.Build}"
            : PartitionInventory.L("安装版本：保留恢复镜像内的系统，以镜像实际信息为准。", "Installed version: keep the system contained in the recovery image.");

    private void UpdateSystemVersion()
    {
        UpgradeLabel.Text = PartitionInventory.L("目标系统：", "Target system: ") + $"SteamOS {OfficialSystem.Version} · build {OfficialSystem.Build}";
        Upgrade310.IsEnabled = UsePrepared.IsChecked != true;
        SystemVersionNote.Text = UsePrepared.IsChecked == true ? SystemVersionSummary() : Upgrade310.IsChecked == true
            ? PartitionInventory.L("先在本页下载并缓存此版本，安装时替换恢复镜像内的系统，匹配设备适配。", "Download and cache this version here first; installation replaces the recovery image system to match device support.")
            : PartitionInventory.L("保留恢复镜像内的系统。部分设备修复/适配需要上方版本，版本不匹配的项目无法安装。", "Keep the recovery image system. Some device repairs require the version above; incompatible items cannot be installed.");
    }

    private void UpdateNavigationState()
    {
        if (!ready) return;
        if (step == 6) checkedAllSteps = true;
        var targetIssue = TargetIssue();
        var sourceIssue = SourceIssue();
        var contentIssue = ContentIssue();
        UpdateSystemVersion();
        var reviewed = targetIssue == null && sourceIssue == null && contentIssue == null && (physicalInstallation
            ? PhysicalConsent.IsChecked == true && acknowledgedSelection == PartitionSelector.Selection
            : reviewSeen);
        var finished = session?.Status is "complete" or "awaiting-device-boot";
        var complete = new[] { targetIssue == null, sourceIssue == null, contentIssue == null, reviewed, true, finished, finished };
        if (finished) Array.Fill(complete, true);
        ModeBannerCard.Visibility = step == 6 && finished ? Visibility.Collapsed : Visibility.Visible;
        NavReview.Text = PartitionInventory.L("04   确认方案", "04   Review");
        NavBoot.Text = PartitionInventory.L("05   启动器安装", "05   Boot manager");
        NavProgress.Text = PartitionInventory.L("06   安装进度", "06   Progress");
        NavResult.Text = PartitionInventory.L("07   安装结果", "07   Result");
        var labels = new[] { NavTarget, NavSource, NavContent, NavReview, NavBoot, NavProgress, NavResult };
        var tabs = new[] { TargetTab, SourceTab, ContentTab, ReviewTab, BootTab, ProgressTab, ResultTab };
        for (var i = 0; i < labels.Length; i++)
        {
            var incomplete = !complete[i] && (departedSteps[i] || checkedAllSteps);
            var configured = complete[i] && (finished || i <= 1 || i == 2 && contentSeen || i == 3 && reviewed || i == 4 && (departedSteps[i] || session != null) || i is 5 or 6);
            labels[i].Foreground = new SolidColorBrush(incomplete ? Color.FromRgb(255, 139, 139) : configured ? Color.FromRgb(134, 239, 172) : i == step ? Colors.White : Color.FromRgb(148, 169, 195));
            tabs[i].Background = i == step ? new SolidColorBrush(Color.FromRgb(37, 63, 95)) : Brushes.Transparent;
            labels[i].FontWeight = i == step ? FontWeights.Bold : FontWeights.Normal;
            labels[i].ToolTip = incomplete ? (i == 0 ? targetIssue : i == 1 ? sourceIssue : i == 2 ? contentIssue : null)
                ?? PartitionInventory.L("未完成，可点击返回配置。", "Incomplete. Select to finish setup.") : configured ? PartitionInventory.L("已完成配置。", "Setup complete.") : null;
        }

        var missing = new List<string>();
        if (targetIssue != null) missing.Add(PartitionInventory.L("安装位置：", "Location: ") + targetIssue);
        if (sourceIssue != null) missing.Add(PartitionInventory.L("准备系统：", "System: ") + sourceIssue);
        if (contentIssue != null) missing.Add(PartitionInventory.L("选择安装内容：", "Contents: ") + contentIssue);
        if (!reviewed) missing.Add(PartitionInventory.L("确认方案：请核对配置并完成确认。", "Review: check and confirm the configuration."));
        if (!finished) missing.Add(operation != null
            ? PartitionInventory.L("安装进度：任务仍在进行，请等待结束。", "Progress: the task is still running.")
            : session == null ? PartitionInventory.L("安装进度：尚未执行安装。", "Progress: installation has not started.")
            : PartitionInventory.L("安装进度：任务未成功完成，请查看结果与日志。", "Progress: the task did not finish successfully. Check the result and logs."));
        // A completed write is a successful installation outcome. Configuration
        // changes and first boot are not failures of the completed operation.
        if (finished) missing.Clear();
        IncompleteCard.Visibility = missing.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        IncompleteHeading.Text = PartitionInventory.L("还有项目未完成", "Some items are incomplete");
        IncompleteItems.Text = string.Join("\n", missing.Select(item => "• " + item));

        var idle = operation == null;
        var written = session?.Physical == true && finished;
        ResultCard.Background = new SolidColorBrush(finished ? Color.FromRgb(236, 253, 243) : Colors.White);
        ResultCard.BorderBrush = new SolidColorBrush(finished ? Color.FromRgb(117, 199, 148) : Color.FromRgb(222, 229, 239));
        ResultTitle.Foreground = new SolidColorBrush(finished ? Color.FromRgb(22, 101, 52) : Color.FromRgb(25, 43, 67));
        RestartPanel.Visibility = written ? Visibility.Visible : Visibility.Collapsed;
        RestartButton.IsEnabled = written && idle && !DownloadsBusy;
        RestartButton.Content = PartitionInventory.L("重启到 SteamOS", "Restart to SteamOS");
        BrowseWorkspaceButton.IsEnabled = idle && !DownloadsBusy && !PartitionSelector.IsBusy;
        WorkspaceCard.Visibility = step <= 4 ? Visibility.Visible : Visibility.Collapsed;
        RefreshWorkspace();
        TargetPage.IsEnabled = idle;
        SourcePage.IsEnabled = idle;
        ContentPage.IsEnabled = idle;
        StoragePage.IsEnabled = false;
        BootPage.IsEnabled = idle;
        PhysicalConsent.IsEnabled = idle;
        NextButton.IsEnabled = BackButton.IsEnabled = InstallerLanguage.IsEnabled = idle && !DownloadsBusy;
        UsePrepared.IsEnabled = optionsPanel.IsEnabled = !DownloadsBusy;
        Upgrade310.IsEnabled = idle && !DownloadsBusy && UsePrepared.IsChecked != true;
        downloadPanel.IsEnabled = !officialDownloadPanel.IsBusy;
        officialDownloadPanel.IsEnabled = !downloadPanel.IsBusy;
        officialDownloadPanel.SetRequired(UsePrepared.IsChecked != true && Upgrade310.IsChecked == true);
        StopButton.IsEnabled = operation != null && !operation.IsCancellationRequested;
        ExportLogButton.Content = PartitionInventory.L("导出详细日志…", "Export logs…");
        ExportLogButton.IsEnabled = !exportingLog && (session != null || LogText.Text.Length > 0);
    }
}
