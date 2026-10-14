using Microsoft.Win32;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace OxpInstaller;
public partial class MainWindow : Window
{
    internal InstallationSession? CompletedSession => session;
    internal bool CloseOnFirstWriteForCheck { get; set; }
    private int step;
    private int sourceSection;
    private void NavigateSourceSection(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string tag }) { sourceSection = int.Parse(tag); ShowStep(1); }
    }
    private void UpdateSourceSection()
    {
        SourceSubitems.Visibility = step == 1 ? Visibility.Visible : Visibility.Collapsed;
        RecoverySourceSection.Visibility = sourceSection == 0 ? Visibility.Visible : Visibility.Collapsed;
        OfficialSourceSection.Visibility = sourceSection == 1 ? Visibility.Visible : Visibility.Collapsed;
        RecoverySourceTab.Background = new SolidColorBrush(sourceSection == 0 ? Color.FromRgb(37,63,95) : Colors.Transparent);
        OfficialSourceTab.Background = new SolidColorBrush(sourceSection == 1 ? Color.FromRgb(37,63,95) : Colors.Transparent);
        NavRecoverySource.Text = PartitionInventory.L("恢复镜像", "Recovery image");
        NavOfficialSource.Text = PartitionInventory.L("3.10 镜像", "3.10 image");
        NavRecoverySource.FontWeight = sourceSection == 0 ? FontWeights.SemiBold : FontWeights.Normal;
        NavOfficialSource.FontWeight = sourceSection == 1 ? FontWeights.SemiBold : FontWeights.Normal;
        if (step == 1)
        {
            PageTitle.Text = sourceSection == 0 ? PartitionInventory.L("准备恢复镜像", "Prepare a recovery image") : PartitionInventory.L("准备 SteamOS 3.10 镜像", "Prepare the SteamOS 3.10 image");
            PageSubtitle.Text = sourceSection == 0 ? PartitionInventory.L("下载或选择本地恢复镜像，然后准备 3.10 系统镜像。", "Download or select a recovery image, then prepare the 3.10 system image.") : PartitionInventory.L("下载或选择本地 3.10 镜像，安装时整合到恢复镜像中。", "Download or select a local 3.10 image to integrate into the recovery image during installation.");
        }
    }
    private CancellationTokenSource? operation;
    private InstallationSession? session;
    private InstallationSession? recent;
    private StreamWriter? journalLog;
    private bool ready;
    private bool closeAfterCleanup;
    private readonly bool physicalInstallation;
    private PartitionSelection? pendingSelection;
    private PartitionSelection? acknowledgedSelection;
    private InstallerOptionsPanel optionsPanel = null!;
    private ImageDownloadPanel downloadPanel = null!;
    private OfficialDownloadPanel officialDownloadPanel = null!;
    private bool DownloadsBusy => downloadPanel.IsBusy || officialDownloadPanel.IsBusy;
    private BootOptionsPanel bootPanel = null!;
    public MainWindow(bool rehearsal = false)
    {
        physicalInstallation = !rehearsal;
        InitializeComponent();
        PartitionSelector.BootPrerequisitesReady = !physicalInstallation;
        PartitionSelector.DefaultCapacityGiB = physicalInstallation ? 64 : 128;
        PartitionSelector.AllowPhysicalDeletion = physicalInstallation;
        optionsPanel = new InstallerOptionsPanel(); ComponentOptionsHost.Children.Add(optionsPanel);
        optionsPanel.Changed += (_, _) => { if (ready) ConfigurationChanged(); };
        bootPanel = new BootOptionsPanel(); BootOptionsHost.Children.Add(bootPanel);
        downloadPanel = new ImageDownloadPanel(); DownloadHost.Children.Add(downloadPanel);
        officialDownloadPanel = new OfficialDownloadPanel(); OfficialDownloadHost.Children.Add(officialDownloadPanel);
        officialDownloadPanel.BusyChanged += _ => UpdateNavigationState();
        downloadPanel.Completed += path => { UsePrepared.IsChecked = false; ImagePath.Text = path; };
        downloadPanel.BusyChanged += busy =>
        {
            UpdateNavigationState();
        };
        ChineseLanguage.IsChecked = InstallerI18n.Language != "en-US";
        EnglishLanguage.IsChecked = InstallerI18n.Language == "en-US";
        InstallerI18n.Apply(this); PartitionSelector.RefreshLanguage(); ready = true; UpdateTargetMode();
        PartitionSelector.Changed += () => { acknowledgedSelection = null; reviewSeen = false; PhysicalConsent.IsChecked = false; if (ready) { ValidationMessage.Text = ""; UpdateNavigationState(); } };
        ImagePath.TextChanged += (_, _) => ConfigurationChanged();
        SourcePage.AddHandler(System.Windows.Controls.Primitives.ToggleButton.CheckedEvent, new RoutedEventHandler((_, _) => ConfigurationChanged()));
        SourcePage.AddHandler(System.Windows.Controls.Primitives.ToggleButton.UncheckedEvent, new RoutedEventHandler((_, _) => ConfigurationChanged()));
        SourcePage.AddHandler(ComboBox.SelectionChangedEvent, new SelectionChangedEventHandler((_, _) => ConfigurationChanged()));
        ContentPage.AddHandler(System.Windows.Controls.Primitives.ToggleButton.CheckedEvent, new RoutedEventHandler((_, _) => ConfigurationChanged()));
        ContentPage.AddHandler(System.Windows.Controls.Primitives.ToggleButton.UncheckedEvent, new RoutedEventHandler((_, _) => ConfigurationChanged()));
        ContentPage.AddHandler(ComboBox.SelectionChangedEvent, new SelectionChangedEventHandler((_, _) => ConfigurationChanged()));
        PhysicalConsent.Checked += (_, _) => { ResetConsentHighlight(); ValidationMessage.Text = ""; UpdateNavigationState(); };
        PhysicalConsent.Unchecked += (_, _) => UpdateNavigationState();
        var local = Path.Combine(InstallerWorkspace.DirectoryPath, "source/steamdeck-oobe-repair-20260707.10-3.8.14.img");
        if (File.Exists(local)) ImagePath.Text = local;
        recent = InstallationController.Latest();
        if (recent != null)
        {
            RecentPanel.Visibility = Visibility.Visible;
            RecentText.Text = recent.Status switch {
                "awaiting-device-boot" => PartitionInventory.L("上次安装写入完成，可以启动 SteamOS。", "The last installation was written successfully. You can boot SteamOS."),
                "complete" => InstallerI18n.T("上次虚拟盘演练已完成。记录中保留了分区写入和启动验证结果。"),
                "running" => InstallerI18n.T("上次任务没有最终结果，或仍在其他窗口运行。请先查看记录；不要将其视为安装完成。"),
                "cancelled" => InstallerI18n.T("上次任务已停止。可以查看记录，再开始一次新的演练。"),
                _ => InstallerI18n.T("上次任务未完成。可以查看记录，排查问题后重新演练。") };
        }
        UpdateRecovery(); Closing += OnClosing; ShowStep(0); UpdateResponsiveLayout();
        RefreshBootPrerequisites();
        BootPrerequisitesCard.Visibility = physicalInstallation ? Visibility.Visible : Visibility.Collapsed;
        if (physicalInstallation) ShowBootPrerequisites(null, null);
    }
    private InstallationTargetKind Kind => ExternalTarget.IsChecked == true ? InstallationTargetKind.ExternalDisk : InstallationTargetKind.InternalShared;
    private InstallationRequest Request
    {
        get
        {
            optionsPanel.ValidateDeckPassword();
            return new(Kind, ImagePath.Text, UsePrepared.IsChecked == true, optionsPanel.Selection,
                Kind == InstallationTargetKind.InternalShared || physicalInstallation ? PartitionSelector.Selection : null,
                physicalInstallation, Upgrade310.IsChecked == true, step == 4 ? bootPanel.Selection : null,
                optionsPanel.InitialDeckPassword, bootPanel.MakeDefaultBoot);
        }
    }
    private void ShowStep(int value)
    {
        if (value != step) departedSteps[step] = true;
        step = value;
        var pages = new[] { TargetPage, SourcePage, ContentPage, ReviewPage, BootPage, ProgressPage, ResultPage };
        for (var i = 0; i < pages.Length; i++) pages[i].Visibility = i == step ? Visibility.Visible : Visibility.Collapsed;
        PageTitle.Text = new[] { InstallerI18n.T("SteamOS，装在你选择的位置"), InstallerI18n.T("准备你的 SteamOS 系统"), InstallerI18n.T("选择安装内容"), InstallerI18n.T("开始前，核对这次方案"), InstallerI18n.T("启动器安装"), InstallerI18n.T("正在完成安装演练"), InstallerI18n.T("本次演练结果") }[step];
        PageSubtitle.Text = new[] { InstallerI18n.T("保留 Windows 双系统，或把完整系统装进外部设备。"), InstallerI18n.T("选好镜像，后面的系统准备交给安装助手。"), PartitionInventory.L("选择设备适配和插件。", "Choose device support and plugins."), InstallerI18n.T("只创建本工具自己的测试盘；所有结果都会记录。"), InstallerI18n.T("rEFInd 启动菜单与配置。"), InstallerI18n.T("保持电脑接通电源，完成前请不要移动工作目录。"), InstallerI18n.T("查看已完成的步骤，以及下一步需要处理的事项。") }[step];
        BackButton.Visibility = step is 1 or 2 or 3 or 4 ? Visibility.Visible : Visibility.Hidden;
        NextButton.Visibility = step == 5 ? Visibility.Collapsed : Visibility.Visible;
        StopButton.Visibility = step == 5 ? Visibility.Visible : Visibility.Collapsed;
        PageFooter.Visibility = step == 5 ? Visibility.Collapsed : Visibility.Visible;
        LogPanel.Visibility = step is 5 or 6 ? Visibility.Visible : Visibility.Collapsed;
        NextButton.Content = step == 4 ? InstallerI18n.T("开始演练") : step == 6 ? InstallerI18n.T("返回首页") : InstallerI18n.T("下一步");
        AdvancedButton.IsEnabled = operation == null;
        ValidationMessage.Text = ""; ValidationMessage.Foreground = new SolidColorBrush(Color.FromRgb(163, 71, 39)); PageScroll.ScrollToTop();
        if(physicalInstallation) { NextButton.Content=step == 4?PartitionInventory.L("开始安装","Install SteamOS"):NextButton.Content; if(step == 5)PageTitle.Text=PartitionInventory.L("正在安装 SteamOS","Installing SteamOS"); if(step == 6)PageTitle.Text=PartitionInventory.L("本次安装结果","Installation result"); }
        InstallerLanguage.IsEnabled = operation == null && !DownloadsBusy;
        if (step == 2) contentSeen = true;
        if (step == 3) { UpdateReview(); reviewSeen = true; }
        UpdateSourceSection();
        bootPanel.SetFirmwareContext(physicalInstallation && Kind == InstallationTargetKind.InternalShared);
        UpdateNavigationState();
        if (step == 5 && operation == null && session == null)
        {
            PageTitle.Text = ProgressTitle.Text = PartitionInventory.L("尚未开始安装", "Installation has not started");
            ProgressMessage.Text = PartitionInventory.L("请先完成配置，再到“确认方案”开始安装。", "Complete setup, then start installation from Review.");
            Progress.IsIndeterminate = false; Progress.Value = 0; ProgressDetail.Text = "";
        }
        if (step == 6 && session == null)
        {
            ResultTitle.Text = PartitionInventory.L("本次任务尚未完成", "This task is not complete");
            ResultMessage.Text = PartitionInventory.L("请根据上方提示补齐项目。可以点击左侧任意步骤返回修改。", "Complete the items above. Select any step on the left to make changes.");
            ResultScope.Text = PartitionInventory.L("浏览页面不会执行安装。", "Browsing pages does not start installation.");
        }
        if (step == 6 && operation != null && session?.Status is not ("complete" or "awaiting-device-boot" or "failed" or "cancelled"))
        {
            ResultTitle.Text = PartitionInventory.L("任务仍在进行", "Task is still running");
            ResultMessage.Text = PartitionInventory.L("可以返回“安装进度”查看当前状态。", "Return to Progress to see the current status.");
            ResultScope.Text = "";
        }
    }
    private void UpdateReview()
    {
        ReviewPartitionHost.Children.Clear();
        ReviewPartitionCard.Visibility = Kind == InstallationTargetKind.InternalShared || physicalInstallation ? Visibility.Visible : Visibility.Collapsed;
        if (Kind == InstallationTargetKind.InternalShared || physicalInstallation)
        {
            try { PartitionPicker.ShowChanges(ReviewPartitionHost, PartitionSelector.Selection); }
            catch (Exception error) when (error is InvalidOperationException or IOException or ArgumentException) { ReviewPartitionHost.Children.Add(new TextBlock { Text = error.Message, TextWrapping = TextWrapping.Wrap }); }
            if(!physicalInstallation) ReviewPartitionHost.Children.Add(new TextBlock { Text = PartitionInventory.L("以上为安装规划。以下演练使用独立 80 GiB 测试盘，规划不会写入所选设备。", "The layout above is a plan. The rehearsal below uses a separate 80 GiB test disk; it does not write this plan to the selected device."), TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,12,0,0) });
        }
        ReviewTarget.Text = Kind == InstallationTargetKind.InternalShared ? InstallerI18n.T("内置硬盘共存方案 · 80 GiB 虚拟测试盘") : InstallerI18n.T("外部完整系统方案 · 80 GiB 虚拟测试盘");
        ReviewSource.Text = (UsePrepared.IsChecked == true ? InstallerI18n.T("已准备系统：") : InstallerI18n.T("恢复镜像：")) + ImagePath.Text;
        ReviewSource.Text += "\n" + SystemVersionSummary();
        ReviewLayout.Text = Kind == InstallationTargetKind.InternalShared
            ? InstallerI18n.T("保留：测试盘已有的 EFI / NTFS 分区与数据。\n新增：SteamOS 启动分区、A/B 系统和独立数据空间。\n测试盘中没有真正的 Windows 操作系统。")
            : InstallerI18n.T("新建：仅包含 SteamOS 的启动分区、A/B 系统和独立数据空间。\n对应实机流程：所选 SD 卡 / SSD 的现有内容将被清空。");
        PhysicalConsent.Visibility=physicalInstallation?Visibility.Visible:Visibility.Collapsed;
        if(physicalInstallation) {
            try {
                var target=PartitionSelector.Selection.Target();
                ReviewTarget.Text=$"{target.Model} · Disk {target.Disk} · {target.Start/1073741824d:F2} GiB";
            }
            catch (Exception error) when (error is InvalidOperationException or IOException or ArgumentException) { ReviewTarget.Text = error.Message; }
            ReviewLayout.Text=PartitionInventory.L("将只向所选未分配范围追加 SteamOS 分区。现有分区保留；需要实机首次启动确认。内置安装添加 UEFI 启动项，可在下一页选择是否设为默认启动项。外部盘通过设备启动菜单启动。系统按所选容量安装，额外容量分配给 SteamOS 数据分区。","Append SteamOS partitions only in the selected unallocated range. Existing partitions are preserved. Internal installation adds a UEFI entry; choose whether to make it the default on the next page. External installation boots from the device menu. The system uses the selected capacity; additional space is assigned to the SteamOS data partition.");
            PageSubtitle.Text=PartitionInventory.L("请核对下面的目标磁盘与写入范围。","Review the target disk and write range below.");
        }
        ReviewExecutionNote.Text = physicalInstallation
            ? PartitionInventory.L("Beta 测试阶段。安装会格式化目标范围内新建的 SteamOS 分区，原有内容将被清空。请保存好重要数据。开始写入时将请求管理员权限。", "Beta software. Installation formats the new SteamOS partitions in the target range, erasing their contents. Back up important data. Administrator permission is requested before writing.")
            : PartitionInventory.L("演练只写入独立虚拟盘，不会写入所选实际设备。", "Rehearsal writes only an independent virtual disk, not the selected physical device.");
        ReviewLayout.Text += "\n\n" + optionsPanel.Describe();
        RefreshWorkspace();
    }
    private void RefreshWorkspace()
    {
        WorkspaceHeading.Text = PartitionInventory.L("工作空间", "Workspace");
        BrowseWorkspaceButton.Content = PartitionInventory.L("选择文件夹…", "Choose folder…");
        WorkspacePath.Text = InstallerWorkspace.DirectoryPath;
        WorkspaceNote.Text = PartitionInventory.L("工作空间至少 45 GiB，建议预留 64 GiB。下载与临时镜像存放于此；旧任务和额外下载需另留空间。", "Workspace: at least 45 GiB; 64 GiB recommended. Downloads and temporary images are stored here; allow extra space for old tasks and additional downloads.");
        if (InstallerWorkspace.LoadError != null) WorkspaceNote.Text = PartitionInventory.L("无法读取之前的工作目录，已使用默认目录；请重新选择。", "The saved workspace could not be loaded. Using the default; choose a folder again.");
        try {
            var available = MediaSpace.Available(Directory.Exists(InstallerWorkspace.DirectoryPath) ? InstallerWorkspace.DirectoryPath : Path.GetPathRoot(InstallerWorkspace.DirectoryPath)!);
            var estimate = MediaSpace.InstallationBudget(physicalInstallation, UsePrepared.IsChecked == true);
            SpaceText.Text = PartitionInventory.L($"可用 {available / 1073741824d:F1} GiB · 本次最低可用空间 {estimate / 1073741824d:F1} GiB{(physicalInstallation ? "" : "（含 80 GiB 演练盘）")}；每阶段会再次核对实际需求。", $"Available {available / 1073741824d:F1} GiB · Minimum free space for this run: {estimate / 1073741824d:F1} GiB{(physicalInstallation ? "" : " (includes an 80 GiB rehearsal disk)")}; actual needs are checked at each stage.");
        } catch (Exception error) { SpaceText.Text = error.Message; }
    }
    private void BrowseWorkspace(object sender, RoutedEventArgs e)
    {
        if (operation != null || DownloadsBusy || PartitionSelector.IsBusy) return;
        var dialog = new OpenFolderDialog { Title = PartitionInventory.L("选择工作空间", "Choose workspace"), InitialDirectory = InstallerWorkspace.DirectoryPath };
        if (dialog.ShowDialog(this) != true) return;
        try {
            InstallerWorkspace.Select(dialog.FolderName);
            session = null; recent = InstallationController.Latest();
            RecentPanel.Visibility = recent == null ? Visibility.Collapsed : Visibility.Visible;
            RecentText.Text = recent == null ? "" : PartitionInventory.L("所选工作空间中有任务记录。", "Task records are available in this workspace.");
            if (UsePrepared.IsChecked == true) ImagePath.Clear();
            downloadPanel.RefreshWorkspace();
            officialDownloadPanel.RefreshWorkspace();
            UpdateRecovery(); ConfigurationChanged(); ValidationMessage.Text = "";
        } catch (Exception error) { ValidationMessage.Text = error.Message; }
        RefreshWorkspace();
    }
    private void LanguageChanged(object sender, RoutedEventArgs e)
    {
        if (!ready || sender is not RadioButton item || operation != null || DownloadsBusy) return;
        var previousAcknowledgement = acknowledgedSelection;
        InstallerI18n.SetLanguage((string)item.Tag); InstallerI18n.Apply(this); optionsPanel.Refresh(); bootPanel.Refresh(); downloadPanel.RefreshLanguage(); officialDownloadPanel.RefreshLanguage(); PartitionSelector.RefreshLanguage(); UpdateTargetMode(); ShowStep(step);
        RefreshBootPrerequisites();
        if (previousAcknowledgement != null && previousAcknowledgement == PartitionSelector.Selection) acknowledgedSelection = previousAcknowledgement;
        if (step == 6 && session != null && operation == null) ShowResult(session);
    }
    private void ChoiceChanged(object sender, RoutedEventArgs e) { if (ready) { acknowledgedSelection = null; reviewSeen = false; ValidationMessage.Text = ""; UpdateTargetMode(); UpdateNavigationState(); } }
    private void UpdateTargetMode()
    {
        bootPanel.SetFirmwareContext(physicalInstallation && Kind == InstallationTargetKind.InternalShared);
        PhysicalConsent.IsChecked=false;
        StopButton.Content=physicalInstallation?PartitionInventory.L("停止安装","Stop installation"):InstallerI18n.T("停止演练");
        ModeBanner.Text=physicalInstallation?PartitionInventory.L("Beta 测试阶段 · 请先备份重要数据。安装将格式化目标 SteamOS 分区。","Beta · Back up important data. Installation formats the target SteamOS partitions."):PartitionInventory.L("开发演练 · 仅写入独立虚拟盘，不写入实际设备。","Developer rehearsal · Writes only an independent virtual disk, not a physical device.");
        ProgressStopNote.Text = physicalInstallation ? PartitionInventory.L("停止会保留已写入的分区。请等待当前操作结束，不要关闭电源。关闭窗口会先进行清理，清理结束后自动关闭。", "Stopping preserves partitions already written. Wait for the current operation to end; do not power off. Closing the window starts cleanup; the window closes automatically when cleanup finishes.") : PartitionInventory.L("可以停止演练。正在写入时，会先结束当前操作并卸载测试盘。不要关闭电源。关闭窗口会先进行清理，清理结束后自动关闭。", "You can stop the rehearsal. A write operation will finish and the test disk will detach first. Do not power off. Closing the window starts cleanup; the window closes automatically when cleanup finishes.");
        PartitionCard.Visibility = Kind == InstallationTargetKind.InternalShared || physicalInstallation ? Visibility.Visible : Visibility.Collapsed;
        PlanningScope.Text = Kind == InstallationTargetKind.InternalShared
            ? PartitionInventory.L("所选磁盘与容量用于安装规划；本次执行仍使用独立的 80 GiB 虚拟测试盘。", "Disk and capacity selections are for planning; execution still uses a separate 80 GiB virtual test disk.")
            : PartitionInventory.L("外部完整系统演练使用新建的 80 GiB 虚拟盘；真实外部设备选择尚未开放。", "The external full-system rehearsal uses a new 80 GiB virtual disk; real external-device selection is not available yet.");
        if(physicalInstallation) PlanningScope.Text=PartitionInventory.L("选择至少 64 GiB 未分配空间，可选 64G、100G、全部空间或自定义容量。也可先删除不再需要的数据分区来释放空间；删除前会单独确认，系统和启动分区受保护。","Choose at least 64 GiB of unallocated space, then select 64G, 100G, all space or a custom capacity. You can first delete an unwanted data partition to free space. Deletion has its own confirmation; system and boot partitions are protected.");
    }
    private void SourceModeChanged(object sender, RoutedEventArgs e) { if (ready) { ImagePath.Clear(); ValidationMessage.Text = ""; } }
    private void BrowseImage(object sender, RoutedEventArgs e)
    {
        if (DownloadsBusy) return;
        var dialog = new OpenFileDialog { Filter = UsePrepared.IsChecked == true ? InstallerI18n.T("已准备系统镜像|prepared.img") : InstallerI18n.T("SteamOS 恢复镜像|*.img;*.img.bz2;*.img.zip"), InitialDirectory = InstallerWorkspace.DirectoryPath };
        if (dialog.ShowDialog(this) == true) { ImagePath.Text = dialog.FileName; ValidationMessage.Text = ""; }
    }
    private void Back(object sender, RoutedEventArgs e)
    {
        if (operation != null || DownloadsBusy) return;
        if (step == 1 && sourceSection == 1) { sourceSection = 0; ShowStep(1); }
        else if (step is 1 or 2 or 3 or 4) ShowStep(step - 1);
    }
    private async void Next(object sender, RoutedEventArgs e)
    {
        if (operation != null || DownloadsBusy) return;
        if (physicalInstallation && (!bootPrerequisitesAcknowledged || BootPrerequisitesOverlay.Visibility == Visibility.Visible)) { ShowBootPrerequisites(null, null); return; }
        try
        {
            if (step == 0)
            {
                if (Kind == InstallationTargetKind.InternalShared || physicalInstallation) _ = PartitionSelector.Selection;
                if (physicalInstallation) OpenSafetyConfirmation(); else ShowStep(1);
            }
            else if (step == 1)
            {
                if (SourceIssue(includeOfficial: sourceSection == 1) is string issue) throw new IOException(issue);
                if (sourceSection == 0 && UsePrepared.IsChecked != true) { sourceSection = 1; ShowStep(1); }
                else ShowStep(2);
            }
            else if (step == 2) { InstallationController.ValidateRequest(Request); ShowStep(3); }
            else if (step == 3) { RequirePhysicalConsent(); InstallationController.ValidateRequest(Request); ShowStep(4); }
            else if (step == 4) { if(physicalInstallation && (PhysicalConsent.IsChecked!=true || acknowledgedSelection != PartitionSelector.Selection)) throw new IOException(PartitionInventory.L("请返回安装位置，核对目标范围并确认备份，然后确认安装方案。","Return to installation location, confirm the target range and backup, then approve the installation plan.")); var request = Request; optionsPanel.ClearSensitiveInputs(); await StartAsync(request); }
            else if (step == 6) { ShowStep(0); }
        }
        catch (Exception error) { ValidationMessage.Text = error.Message; }
    }
    private void RequirePhysicalConsent()
    {
        if (physicalInstallation && PhysicalConsent.IsChecked != true)
        {
            PhysicalConsent.BringIntoView(); PhysicalConsent.Focus();
            var brush = new SolidColorBrush(Color.FromRgb(180, 35, 24));
            PhysicalConsentBorder.BorderBrush = brush;
            if (SystemParameters.ClientAreaAnimation)
                brush.BeginAnimation(SolidColorBrush.ColorProperty, new ColorAnimation(
                    Color.FromRgb(180, 35, 24), Color.FromRgb(242, 199, 149), TimeSpan.FromMilliseconds(450))
                    { AutoReverse = true, RepeatBehavior = new RepeatBehavior(3), FillBehavior = FillBehavior.Stop });
        }
        if (physicalInstallation && (PhysicalConsent.IsChecked != true || acknowledgedSelection != PartitionSelector.Selection))
            throw new IOException(PartitionInventory.L("请先核对目标范围并确认备份，然后勾选确认安装方案。", "Review the target and backup, then approve the installation plan."));
    }
    private void ResetConsentHighlight() => PhysicalConsentBorder.BorderBrush = new SolidColorBrush(Color.FromRgb(196, 138, 50));
    private void OpenSafetyConfirmation()
    {
        var selection = PartitionSelector.Selection;
        if (selection.Example) throw new InvalidOperationException(PartitionInventory.L("这是示例布局，不能实际安装。请读取本机磁盘并选择未分配空间。", "This is an example layout. Read this PC's disks and select unallocated space to install."));
        var target = selection.Target();
        pendingSelection = selection;
        SafetyTarget.Text = $"{target.Model} · Disk {target.Disk}\n" + PartitionInventory.L(
            $"未分配范围：起点 {target.Start / (double)PartitionInventory.GiB:F2} GiB · 所选容量 {PartitionInventory.SizeText(selection.Capacity)}",
            $"Unallocated range: starts at {target.Start / (double)PartitionInventory.GiB:F2} GiB · Selected capacity {PartitionInventory.SizeText(selection.Capacity)}");
        SafetyMessage.Text = PartitionInventory.L(
            "安装将格式化此范围内新建的 SteamOS 分区，分区内原有内容会被清空，无法通过安装助手恢复。已有 Windows 和其他分区将保留。\n\n此项目仍处于 Beta 测试阶段，可能存在缺陷。请先备份重要数据并准备恢复介质。\n\n此处确认后进入系统准备，最后核对方案并点击“开始安装”才会执行安装。",
            "Installation formats the new SteamOS partitions in this range. Their contents will be erased and cannot be restored by this installer. Existing Windows and other partitions are preserved.\n\nThis project is still in Beta and may contain defects. Back up important data and prepare recovery media.\n\nContinue to system preparation. Installation begins only after the final review and Install SteamOS.");
        WizardShell.IsEnabled = false; SafetyOverlay.Visibility = Visibility.Visible; SafetyCancel.Focus();
    }
    private void CancelSafety(object sender, RoutedEventArgs e)
    {
        pendingSelection = null; SafetyOverlay.Visibility = Visibility.Collapsed; WizardShell.IsEnabled = true; NextButton.Focus();
    }
    private void ConfirmSafety(object sender, RoutedEventArgs e)
    {
        if (pendingSelection == null) return;
        try
        {
            if (pendingSelection != PartitionSelector.Selection) throw new InvalidOperationException(PartitionInventory.L("安装范围已变化，请重新确认。", "The target range changed. Confirm it again."));
            acknowledgedSelection = pendingSelection; CancelSafety(sender, e); ShowStep(1);
        }
        catch (Exception error) { CancelSafety(sender, e); ValidationMessage.Text = error.Message; }
    }
    private void LayoutChanged(object sender, SizeChangedEventArgs e) => UpdateResponsiveLayout();
    private void LogLayoutChanged(object sender, SizeChangedEventArgs e) => UpdateLogLayout();
    private void UpdateLogLayout()
    {
        if (LogText == null || PageScroll == null || step is not (5 or 6)) return;
        var pageHeight = step == 5 ? ProgressPage.ActualHeight : ResultPage.ActualHeight;
        // Fill spare vertical space; short windows can still scroll to the complete log.
        LogText.Height = Math.Max(180, PageScroll.ActualHeight - pageHeight - 68);
    }
    private void UpdateResponsiveLayout()
    {
        if (MainContent == null || TargetChoices == null) return;
        var width = WindowRoot.ActualWidth > 0 ? WindowRoot.ActualWidth : Width;
        var compact = width < 960;
        var stackedChoices = width < 800;
        SidebarColumn.Width = new GridLength(compact ? 152 : 176);
        MainContent.Margin = compact ? new Thickness(14,12,14,10) : new Thickness(20,16,20,12);
        PageTitle.FontSize = compact ? 20 : 22;
        // Keep one vertical gesture surface; do not nest a scrollable disk table inside it.
        PartitionSelector.FreeColumn.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        PartitionSelector.TypeColumn.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        PartitionSelector.FitColumns();
        Grid.SetColumnSpan(InternalTarget, stackedChoices ? 2 : 1);
        Grid.SetColumn(ExternalTarget, stackedChoices ? 0 : 1); Grid.SetRow(ExternalTarget, stackedChoices ? 1 : 0); Grid.SetColumnSpan(ExternalTarget, stackedChoices ? 2 : 1);
        InternalTarget.Margin = new Thickness(0,0,stackedChoices ? 0 : 10,12);
        UpdateLogLayout();
    }
    private void ToggleFullscreen(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
    }
    private void WindowKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape && BootPrerequisitesOverlay.Visibility == Visibility.Visible) { Close(); e.Handled = true; }
        else if (e.Key == Key.Escape && SafetyOverlay.Visibility == Visibility.Visible) { CancelSafety(sender,e); e.Handled = true; }
        else if (e.Key == Key.F11 || e.Key == Key.Escape && WindowState == WindowState.Maximized) { ToggleFullscreen(sender,e); e.Handled = true; }
    }
    private void ExitWindow(object sender, RoutedEventArgs e) => Close();
    private void Log(string message) => Dispatcher.Invoke(() =>
    {
        var text = Regex.Replace(message, @"\x1b\[[0-9;?]*[A-Za-z]|\x1b[78]", "");
        journalLog?.Write(text);
        LogText.AppendText(text); if (LogText.Text.Length > 70000) LogText.Text = LogText.Text[^50000..]; LogText.ScrollToEnd();
        ExportLogButton.IsEnabled = !exportingLog;
    });
    private void Report(InstallationProgress progress) => Dispatcher.Invoke(() =>
    {
        if (CloseOnFirstWriteForCheck && progress.Stage == "writing" && progress.Percent > 78
            && progress.Step?.StartsWith("04.", StringComparison.Ordinal) == true)
        { CloseOnFirstWriteForCheck = false; Close(); return; }
        ProgressTitle.Text = progress.Stage switch { "preparing" => PartitionInventory.L("准备系统", "Preparing system"), "components" => PartitionInventory.L("配置及复核组件", "Installing and checking components"), "bootloader" => PartitionInventory.L("安装 rEFInd", "Installing rEFInd"), "permission" => InstallerI18n.T("等待管理员权限"), "writing" => PartitionInventory.L("写入并读回核对", "Writing and verifying"), "booting" => PartitionInventory.L("验证 SteamOS 启动", "Verifying SteamOS boot"), "complete" => InstallerI18n.T("演练完成"), "failed" => PartitionInventory.L("任务未完成", "Task incomplete"), "cancelled" => PartitionInventory.L("任务已停止", "Task stopped"), _ => InstallerI18n.T("正在结束任务") };
        if(session?.Physical==true && progress.Stage=="complete") ProgressTitle.Text=PartitionInventory.L("磁盘写入完成","Disk writing completed");
        ProgressMessage.Text = InstallerI18n.T(progress.Message);
        ProgressArchiveHint.Visibility = progress.Stage == "preparing"
            && progress.Step == "01.01"
            && session?.Source.EndsWith(".img.bz2", StringComparison.OrdinalIgnoreCase) == true
            ? Visibility.Visible : Visibility.Collapsed;
        Progress.IsIndeterminate = false;
        if (progress.Percent is double percent && double.IsFinite(percent)) Progress.Value = Math.Max(Progress.Value, Math.Clamp(percent, 0, 100));
        ProgressDetail.Text = PartitionInventory.L($"总进度 {Progress.Value:F2}% · 阶段 {progress.Step ?? "—"}", $"Overall progress {Progress.Value:F2}% · Step {progress.Step ?? "—"}");
        System.Windows.Automation.AutomationProperties.SetName(Progress, ProgressDetail.Text);
    });
    internal async Task StartAsync(InstallationRequest request)
    {
        if (operation != null) throw new InvalidOperationException(InstallerI18n.T("已有任务正在运行。"));
        InstallationController.ValidateRequest(request);
        session = null; Progress.Value = 0;
        operation = new CancellationTokenSource(); StopButton.IsEnabled = true; ShowStep(5); LogText.Clear(); LogExpander.IsExpanded = false;
        try
        {
            session = await InstallationController.RunAsync(request, Report, Log, operation.Token, state => Dispatcher.Invoke(() =>
            {
                session = state;
                journalLog = new StreamWriter(new FileStream(Path.Combine(InstallationController.SessionDirectory(state), "ui.log"), FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
            }));
            ShowResult(session);
        }
        catch (Exception error)
        {
            Log(error.ToString()); ShowStep(6); ResultTitle.Text = InstallerI18n.T("无法开始演练"); ResultMessage.Text = error.Message;
            ResultScope.Text = InstallerI18n.T("查看任务记录后重试。没有完整写入与启动证据时，不会显示安装完成。");
        }
        finally { FinishOperation(); }
    }
    private void ShowResult(InstallationSession state)
    {
        session = state;
        recent = state; RecentPanel.Visibility = Visibility.Visible;
        RecentText.Text = state.Status == "complete" ? InstallerI18n.T("上次虚拟盘演练已完成，可查看写入与启动记录。") : InstallerI18n.T("上次任务未完成，可查看记录后重新演练。");
        UpdateRecovery(); ShowStep(6);
        ResultTitle.Text = state.Status == "complete" ? InstallerI18n.T("SteamOS 启动演练成功") : state.Status == "cancelled" ? InstallerI18n.T("演练已停止") : InstallerI18n.T("演练未完成");
        ResultMessage.Text = state.Status == "complete"
            ? InstallerI18n.T("系统分区已写入并读回核对；独立 UEFI 虚拟机已进入 SteamOS 登录提示。测试盘已卸载。")
            : state.Status == "cancelled" ? (state.Error == InstallerI18n.T("管理员权限请求已取消。") ? state.Error : InstallerI18n.T("本次演练已停止，测试文件和日志已保留。"))
            : state.Error ?? InstallerI18n.T("任务没有提供完成证据，请查看详细日志。");
        ResultScope.Text = state.Status == "complete"
            ? InstallerI18n.T("后续还需完成真实磁盘与主机引导接入，再到掌机验证双启动和驱动。当前电脑无需重启。")
            : InstallerI18n.T("保留本次文件与日志。若显示“复查并继续”，可以恢复本次演练；重新演练仍会使用新的测试盘。");
        if(state.Physical) {
            var written = state.Status is "awaiting-device-boot" or "complete";
            PageTitle.Text=PartitionInventory.L("本次安装结果","Installation result");
            ResultTitle.Text=written?PartitionInventory.L("写入完成","Writing complete"):PartitionInventory.L("安装未完成","Installation incomplete");
            ResultMessage.Text=written?PartitionInventory.L("SteamOS 系统分区已写入，并已完成读回核对。","SteamOS system partitions have been written and read-back verification is complete."):state.Error;
            ResultScope.Text=written ? BootResultGuidance(state) : PartitionInventory.L("保留任务目录。若中断，不要自动删除已创建分区或重复安装；先检查 physical-state.json 中的设备与完成记录。","Keep the task directory. If interrupted, review physical-state.json before deleting partitions or reinstalling.");
            RecentText.Text=ResultTitle.Text;
        }
        var componentReport = Path.Combine(InstallationController.SessionDirectory(state), "components.json");
        if (File.Exists(componentReport))
        {
            using var results = System.Text.Json.JsonDocument.Parse(File.ReadAllText(componentReport));
            var catalog = InstallerOptions.Catalog;
            var names = catalog.Repairs.Concat(catalog.Plugins).ToDictionary(x => x.Id);
            var groups = results.RootElement.EnumerateArray().GroupBy(x => x.GetProperty("id").GetString()!).ToArray();
            var skipped = groups.Count(group => group.Any(x => x.GetProperty("status").GetString() != "files_installed"));
            if (skipped > 0)
                ResultMessage.Text += "\n\n" + PartitionInventory.L($"有 {skipped} 项所选组件被跳过，相关功能不可用，详情见下方。可补齐资源后再安装这些组件。", $"{skipped} selected component(s) were skipped; their features are unavailable. See below. Install them later after supplying the resources.");
            var summaries = groups.OrderBy(group => group.All(x => x.GetProperty("status").GetString() == "files_installed")).Select(group =>
            {
                var failed = group.Where(x => x.GetProperty("status").GetString() != "files_installed").ToArray();
                var label = names.TryGetValue(group.Key, out var item) ? (InstallerI18n.Language == "en-US" ? item.En : item.Zh)
                    : group.Key == "deck-access" ? PartitionInventory.L("账户与 SSH 设置", "Account and SSH settings") : PartitionInventory.L("KDE 语言", "KDE language");
                return label + ": " + (failed.Length == 0 ? PartitionInventory.L("文件已部署；首次启动核对激活", "files installed; activation checked at first boot")
                    : PartitionInventory.L("已跳过 / 不可用：", "skipped / unavailable: ") + string.Join("; ", failed.Select(x =>
                        PartitionInventory.L("系统槽 ", "slot ") + x.GetProperty("slot").GetString() + " — " + InstallerI18n.Diagnostic(x.GetProperty("reason").GetString()!))));
            });
            ResultScope.Text += "\n\n" + PartitionInventory.L("所选组件安装结果", "Selected component results") + "\n" + string.Join("\n", summaries);
        }
    }
    private void UpdateRecovery()
    {
        var available = !physicalInstallation && InstallationController.CanResume(recent);
        ResumeRecentButton.Visibility = ResumeResultButton.Visibility = available ? Visibility.Visible : Visibility.Collapsed;
        if (available) RecentText.Text = InstallerI18n.T("上次演练未完成，可以复查已写入的内容，再继续剩余步骤。");
    }
    private async void ResumeRecent(object sender, RoutedEventArgs e)
    { if (operation == null && recent != null) await ResumeAsync(recent); }
    internal async Task ResumeAsync(InstallationSession selected)
    {
        if (operation != null || DownloadsBusy) return;
        session = selected; Progress.Value = 0;
        operation = new CancellationTokenSource(); StopButton.IsEnabled = true; ShowStep(5); LogText.Clear(); LogExpander.IsExpanded = false;
        try
        {
            var path = Path.Combine(InstallationController.SessionDirectory(selected), "ui-resume-" + Guid.NewGuid().ToString("N") + ".log");
            MediaSource.Ordinary(path, InstallationController.Work, false);
            journalLog = new StreamWriter(new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
            session = await InstallationController.ResumeAsync(selected, Report, Log, operation.Token);
            ShowResult(session);
        }
        catch (Exception error)
        {
            Log(error.ToString()); ShowStep(6); ResultTitle.Text = InstallerI18n.T("无法继续演练"); ResultMessage.Text = error.Message;
            ResultScope.Text = InstallerI18n.T("原任务记录已保留。请先处理提示中的问题，再重试。");
        }
        finally { FinishOperation(); }
    }
    internal void FinishOperation()
    {
        journalLog?.Dispose(); journalLog = null;
        operation?.Dispose(); operation = null;
        UpdateRecovery(); UpdateNavigationState();
        if (closeAfterCleanup) { closeAfterCleanup = false; Close(); }
    }
    private void Stop(object sender, RoutedEventArgs e)
    { operation?.Cancel(); StopButton.IsEnabled = false; ProgressMessage.Text = InstallerI18n.T("正在停止并清理，请稍候…"); }
    private bool exportingLog;
    private async void ExportLog(object sender, RoutedEventArgs e)
    {
        if (exportingLog) return;
        var dialog = new SaveFileDialog
        {
            Title = PartitionInventory.L("导出详细日志", "Export detailed logs"),
            Filter = PartitionInventory.L("诊断日志压缩包|*.zip", "Diagnostic log archive|*.zip"),
            FileName = "SteamOS-logs-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".zip",
            DefaultExt = ".zip", AddExtension = true
        };
        if (dialog.ShowDialog(this) != true) return;
        exportingLog = true;
        ExportLogButton.IsEnabled = false;
        try
        {
            journalLog?.Flush();
            var selected = session;
            var displayedLog = LogText.Text;
            var workspace = InstallationController.Work;
            await Task.Run(() => DiagnosticLogExport.Write(dialog.FileName, selected, displayedLog, workspace));
            ValidationMessage.Text = PartitionInventory.L("日志已导出，可将压缩包发给开发者：", "Logs exported. Send this archive to the developer: ") + dialog.FileName;
        }
        catch (Exception error)
        {
            ValidationMessage.Foreground = new SolidColorBrush(Color.FromRgb(163, 71, 39));
            ValidationMessage.Text = PartitionInventory.L("导出失败，请选择其他保存位置重试：", "Export failed. Try another save location: ") + error.Message;
        }
        finally { exportingLog = false; UpdateNavigationState(); }
    }
    private void OpenAdvanced(object sender, RoutedEventArgs e)
    { if (operation == null && DebugMode.IsChecked == true) new AdvancedWindow { Owner = this }.ShowDialog(); }
    private void DebugModeChanged(object sender, RoutedEventArgs e)
    {
        if (!ready) return;
        var enabled = DebugMode.IsChecked == true;
        AdvancedButton.Visibility = DeveloperOptions.Visibility = enabled ? Visibility.Visible : Visibility.Collapsed;
        PartitionSelector.SetDebugMode(enabled);
        if (!enabled) { DeveloperOptions.IsExpanded = false; UsePrepared.IsChecked = false; }
        acknowledgedSelection = null;
        ConfigurationChanged();
    }
    private void OpenRecent(object sender, RoutedEventArgs e) { if (recent != null) OpenFolder(InstallationController.SessionDirectory(recent)); }
    private void OpenSession(object sender, RoutedEventArgs e) { if (session != null) OpenFolder(InstallationController.SessionDirectory(session)); }
    private void OpenFolder(string path)
    { try { Process.Start(new ProcessStartInfo("explorer.exe") { ArgumentList = { path }, UseShellExecute = true }); } catch (Exception e) { ValidationMessage.Text = e.Message; } }
    private void OnClosing(object? sender, CancelEventArgs e)
    { if (PartitionSelector.IsBusy) { e.Cancel = true; } else if (DownloadsBusy) { e.Cancel = true; if (officialDownloadPanel.IsBusy) officialDownloadPanel.Pause(); else downloadPanel.Pause(); } else if (operation != null) { e.Cancel = true; closeAfterCleanup = true; Stop(this, new RoutedEventArgs()); } }
    internal void PreviewStep(int previewStep)
    {
        if (previewStep is < 0 or > 6) throw new ArgumentOutOfRangeException(nameof(previewStep));
        ShowStep(previewStep);
        if (previewStep == 5)
        {
            Progress.Value = 0;
            Report(new("writing", PartitionInventory.L("示例：正在读回核对 rootfs-A", "Example: reading back rootfs-A"), 86.2, "04.42"));
            LogText.Text = PartitionInventory.L("界面预览 · 以下为示例日志，未执行安装。", "UI preview · Sample logs only; no installation was performed.") + "\n[preview] Preparing SteamOS\n[preview] Configuring selected components\n[preview] Writing rootfs-A\n[preview] Readback verification: 62%\n";
            UpdateNavigationState();
        }
        if (previewStep == 6) { ResultTitle.Text = InstallerI18n.T("界面预览 · 演练完成示例"); ResultMessage.Text = InstallerI18n.T("实际任务完成后，这里会显示分区写入与独立启动的验证结果。"); ResultScope.Text = InstallerI18n.T("此页面仅用于界面检查，不代表已执行安装。"); }
    }
}





