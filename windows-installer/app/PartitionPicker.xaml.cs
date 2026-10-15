using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public partial class PartitionPicker : UserControl
{
    private string? snapshot;
    private bool example, updating, busy;
    private bool automaticReadAttempted;
    // Synthetic WPF checks must not race a live inventory read.
    internal bool AutomaticReadEnabled { get; set; } = true;
    internal bool BootPrerequisitesReady { get; set; } = true;
    private SpaceChoice? gap;
    public event Action? Changed;
    private static string L(string zh, string en) => PartitionInventory.L(zh, en);
    public PartitionPicker()
    {
        InitializeComponent(); RefreshLanguage();
        Loaded += async (_, _) => await ReadDisksOnOpenAsync();
        IsVisibleChanged += async (_, _) => await ReadDisksOnOpenAsync();
    }
    internal async Task ReadDisksOnOpenAsync()
    {
        if (!BootPrerequisitesReady || !AutomaticReadEnabled || !IsLoaded || !IsVisible || automaticReadAttempted || busy || snapshot != null) return;
        await ReadDisksAsync();
    }
    internal decimal DefaultCapacityGiB { get; set; } = 128;
    internal bool AllowPhysicalDeletion { get; set; } = true;
    internal bool IsBusy => busy;
    internal string? InventorySnapshot => snapshot;
    internal bool IsExampleSnapshot => example;
    private bool debugMode;
    internal void SetDebugMode(bool enabled)
    {
        debugMode = enabled;
        ExampleButton.Visibility = enabled ? Visibility.Visible : Visibility.Collapsed;
        if (!enabled && example) { Clear(); SelectionHint.Text = ""; }
        RefreshLanguage();
    }
    private void PickerSizeChanged(object sender, SizeChangedEventArgs e) => FitColumns();
    internal void FitColumns()
    {
        if (Partitions == null || Partitions.ActualWidth < 200) return;
        var available = Math.Max(200, Partitions.ActualWidth - 4);
        var details = FreeColumn.Visibility == Visibility.Visible;
        SizeColumn.Width = new DataGridLength(82);
        FreeColumn.Width = new DataGridLength(82);
        var flexible = available - (details ? 164 : 82);
        NameColumn.Width = new DataGridLength(flexible * (details ? .36 : .48));
        TypeColumn.Width = new DataGridLength(flexible * .22);
        StatusColumn.Width = new DataGridLength(flexible * (details ? .42 : .52));
    }
    public PartitionSelection Selection
    {
        get
        {
            if (busy || snapshot == null || gap == null) throw new InvalidOperationException(L("请选择一段可安装的未分配空间。", "Select an eligible unallocated region."));
            var selected = new PartitionSelection(snapshot, example, gap.Disk, gap.Start, PartitionInventory.ParseCapacity(CapacityInput.Text, gap.Size), AlignRight.IsChecked == true);
            selected.Target(); return selected;
        }
    }
    public void RefreshLanguage()
    {
        Heading.Text = L("选择磁盘与安装空间", "Choose disk and installation space");
        RefreshButton.Content = L("读取 / 刷新本机磁盘", "Read / refresh this PC's disks");
        DiskReadStatus.Text = L("正在读取…", "Reading…");
        ExampleButton.Content = L("使用示例布局", "Use example layout");
        DeletePartitionButton.Content = L("删除选定分区…", "Delete selected partition…");
        FormatRemainingButton.Content = L("将剩余空间格式化为 NTFS…", "Format remaining space as NTFS…");
        FormatRemainingHint.Text = L("保留所选 SteamOS 容量（可选 64 GiB），将同一段空间的余量建为共享文件分区。确认后立即格式化；分区起点 1 MiB 对齐（满足 4K 对齐），4096 字节簇。", "Reserve the selected SteamOS capacity (64 GiB available) and create a shared-file partition in the rest of this region. Formats immediately after confirmation; partition start aligned to 1 MiB (4K aligned), 4096-byte clusters.");
        NameColumn.Header = L("分区 / 空间", "Partition / region"); SizeColumn.Header = L("容量", "Size");
        FreeColumn.Header = L("可用", "Free"); TypeColumn.Header = L("类型", "Type"); StatusColumn.Header = L("状态", "Status");
        CapacityLabel.Text = L("SteamOS 安装容量", "SteamOS capacity"); AllSpaceButton.Content = L("使用全部空间", "Use all space");
        PlacementLabel.Text = L("安装区位置", "Installation placement");
        AlignLeft.Content = L("靠左", "Left");
        AlignRight.Content = L("靠右（默认）", "Right (default)");
        PlacementHint.Text = L("靠左：SteamOS 在前、余量在后；靠右：余量在前、SteamOS 在后。两种方式均按 1 MiB 对齐，满足 4K 对齐。", "Left: SteamOS first, remainder after. Right: remainder first, SteamOS after. Both use 1 MiB boundaries for 4K alignment.");
        AutomationProperties.SetName(Disks, L("目标磁盘", "Target disk"));
        AutomationProperties.SetName(Partitions, L("分区与未分配空间", "Partitions and unallocated space"));
        AutomationProperties.SetName(CapacityInput, CapacityLabel.Text);
        AutomationProperties.SetName(Capacity64Button, L("安装容量 64 GiB", "Install using 64 GiB"));
        AutomationProperties.SetName(Capacity100Button, L("安装容量 100 GiB", "Install using 100 GiB"));
        if (snapshot != null && !busy)
        {
            var disk = (Disks.SelectedItem as InventoryDisk)?.Number; var start = (Partitions.SelectedItem as PartitionRow)?.Start; var input = CapacityInput.Text;
            LoadSnapshot(snapshot, example);
            Disks.SelectedItem = Disks.Items.Cast<InventoryDisk>().FirstOrDefault(d => d.Number == disk);
            Partitions.SelectedItem = Partitions.Items.Cast<PartitionRow>().FirstOrDefault(r => r.Start == start);
            CapacityInput.Text = input;
        }
        else if (!busy) InventoryStatus.Text = debugMode
            ? L("读取本机磁盘，或使用明确标记的示例布局体验分区规划。", "Read this PC's disks, or explore partition planning with a labeled example.")
            : L("请读取本机磁盘，选择安装位置。", "Read this PC's disks to choose an installation location.");
    }
    internal void LoadSnapshot(string json, bool isExample)
    {
        Clear();
        var disks = PartitionInventory.Read(json);
        snapshot = json; example = isExample; Disks.ItemsSource = disks;
        InventoryStatus.Text = (isExample ? L("示例布局 · 非实际设备", "Example layout · not a real device") : L("本机磁盘快照 · 只读规划", "This PC's disk snapshot · read-only planning"))
            + "\n" + L("选择未分配空间安装；可删除不再需要的数据分区或未识别文件系统分区来释放空间。未识别不代表空盘，删除会清空整个分区。", "Choose unallocated space to install. Delete unwanted data or unrecognized filesystem partitions to free space. Unrecognized does not mean empty; deletion erases the entire partition.");
        if (disks.Length > 0) Disks.SelectedIndex = 0;
        else SelectionHint.Text = debugMode ? L("未发现磁盘。可重试读取，或使用示例布局。", "No disks found. Retry or use the example layout.") : L("未发现磁盘，请检查设备连接后重新读取。", "No disks found. Check the device connection and retry.");
    }
    private void Clear()
    {
        snapshot = null; gap = null; example = false; Disks.ItemsSource = null; Partitions.ItemsSource = null;
        CapacityInput.Clear(); CapacityPanel.IsEnabled = false; ChangesHost.Children.Clear(); CapacityHint.Text = "";
        DeletePartitionButton.IsEnabled = false;
        FormatRemainingButton.IsEnabled = false;
        Changed?.Invoke();
    }
    private async void ReadDisks(object sender, RoutedEventArgs e) => await ReadDisksAsync();
    private async Task ReadDisksAsync()
    {
        if (busy) return;
        automaticReadAttempted = true;
        busy = true; RefreshButton.IsEnabled = ExampleButton.IsEnabled = false;
        DiskReadStatus.Visibility = Visibility.Visible;
        Clear();
        InventoryStatus.Text = L("正在读取磁盘布局…", "Reading disk layout…");
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            var json = await Backend.PowerShellAsync("read-disks.ps1", [], _ => { }, timeout.Token);
            LoadSnapshot(json, false);
        }
        catch (Exception error)
        {
            Clear(); InventoryStatus.Text = L("读取失败：", "Read failed: ") + error.Message;
            SelectionHint.Text = debugMode ? L("请重试读取；也可使用示例布局进行规划演示。", "Retry, or use the example layout to explore planning.") : L("请检查设备连接和管理员权限，然后重新读取。", "Check the device connection and administrator permission, then retry.");
        }
        finally { busy = false; DiskReadStatus.Visibility = Visibility.Collapsed; RefreshButton.IsEnabled = ExampleButton.IsEnabled = true; Changed?.Invoke(); }
    }
    private void UseExample(object sender, RoutedEventArgs e) { if (debugMode && !busy) LoadSnapshot(PartitionInventory.ExampleJson, true); }
    private void DiskChanged(object sender, SelectionChangedEventArgs e)
    {
        gap = null; CapacityInput.Clear(); ChangesHost.Children.Clear(); CapacityPanel.IsEnabled = false;
        Partitions.ItemsSource = (Disks.SelectedItem as InventoryDisk)?.Rows;
        SelectionHint.Text = (Disks.SelectedItem as InventoryDisk)?.Rows.Any(r => r.Space != null) == true
            ? L("请选择标记为“可安装 SteamOS”的未分配空间。", "Select unallocated space marked as available for SteamOS.")
            : L("需要至少 64 GiB 连续未分配空间。可删除不再需要的数据分区来释放空间；系统、启动和恢复分区受保护。", "At least 64 GiB of contiguous unallocated space is required. Delete an unwanted data partition to free space; system, boot and recovery partitions are protected.");
        Changed?.Invoke();
    }
    private void PartitionChanged(object sender, SelectionChangedEventArgs e)
    {
        gap = (Partitions.SelectedItem as PartitionRow)?.Space;
        DeletePartitionButton.IsEnabled = !busy && (example || AllowPhysicalDeletion) && (Partitions.SelectedItem as PartitionRow)?.CanDelete == true;
        CapacityPanel.IsEnabled = gap != null; ChangesHost.Children.Clear(); CapacityHint.Text = "";
        if (gap == null)
        {
            SelectionHint.Foreground = Brushes.Sienna;
            CapacityInput.Clear();
            SelectionHint.Text = (Partitions.SelectedItem as PartitionRow)?.CanDelete == true
                ? (!example && !AllowPhysicalDeletion ? L("演练模式不会删除真实分区。可使用示例布局体验删除。", "Rehearsal mode cannot delete real partitions. Use the example layout to try deletion.")
                    : L("可以删除此数据分区以释放空间。整个分区内的文件都会丢失，请先备份；点击下方按钮核对详情。", "You can delete this data partition to free space. All its files will be lost; back them up first, then review the details below."))
                : (Partitions.SelectedItem as PartitionRow)?.Status ?? L("请选择未分配空间。", "Select unallocated space.");
            Changed?.Invoke(); return;
        }
        SelectionHint.Foreground = new SolidColorBrush(Color.FromRgb(53,84,122));
        SelectionHint.Text = L("已有分区将保留。只在所选未分配空间内规划 SteamOS。", "Existing partitions are kept. SteamOS is planned only inside the selected unallocated region.");
        CapacityInput.Text = Math.Min(DefaultCapacityGiB, decimal.Floor(gap.Size / (decimal)PartitionInventory.GiB)).ToString(CultureInfo.InvariantCulture);
        UpdatePlan();
    }
    private async void DeletePartition(object sender, RoutedEventArgs e)
    {
        if (busy || snapshot == null || (!example && !AllowPhysicalDeletion) || Partitions.SelectedItem is not PartitionRow { CanDelete: true } row) return;
        var request = new PartitionDeleteRequest(snapshot, example, row.Disk, row.Start, InstallerI18n.Language);
        var owner = Window.GetWindow(this);
        if (example)
        {
            var dialog = PartitionDeletion.Confirmation(request); dialog.Owner = owner; dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner;
            if (dialog.ShowDialog() != true) return;
            SelectReleasedSpace(PartitionDeletion.Simulate(request), true, request);
            return;
        }
        busy = true; gap = null; Changed?.Invoke();
        if (owner != null) owner.IsEnabled = false;
        DeletePartitionButton.IsEnabled = false;
        InventoryStatus.Text = L("请在管理员确认窗口核对删除目标。完成后将重新读取磁盘…", "Review the target in the administrator confirmation window. Disks will be refreshed afterward…");
        string? failure = null; bool deleted = false;
        try { deleted = await PartitionDeletion.RunAsync(request); }
        catch (Exception error) { failure = error.Message; }
        // Even cancellation/failure invalidates the old snapshot: the outcome may be uncertain.
        Clear();
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            var fresh = await Backend.PowerShellAsync("read-disks.ps1", [], _ => { }, timeout.Token);
            busy = false;
            if (deleted) SelectReleasedSpace(fresh, false, request); else LoadSnapshot(fresh, false);
            if (!deleted) InventoryStatus.Text = failure == null ? L("已取消删除。磁盘列表已刷新，请重新选择。", "Deletion cancelled. Disks refreshed; select again.")
                : L("删除未确认完成。已刷新磁盘，请核对当前布局：\n", "Deletion was not confirmed. Disks refreshed; review the current layout:\n") + failure;
        }
        catch (Exception error)
        {
            Clear(); InventoryStatus.Text = (deleted ? L("删除已完成，但刷新失败。", "Deletion completed, but refresh failed.") : L("未能确认磁盘当前状态。", "Could not confirm the current disk state."))
                + L("请点击“读取 / 刷新本机磁盘”后再继续。\n", "Read / refresh disks before continuing.\n") + (failure == null ? "" : failure + "\n") + error.Message;
        }
        finally { busy = false; if (owner != null) owner.IsEnabled = true; Changed?.Invoke(); }
    }
    internal void SelectReleasedSpace(string json, bool isExample, PartitionDeleteRequest request)
    {
        LoadSnapshot(json, isExample);
        Disks.SelectedItem = Disks.Items.Cast<InventoryDisk>().SingleOrDefault(d => d.Number == request.Disk);
        var released = Partitions.Items.Cast<PartitionRow>().FirstOrDefault(r => r.Space != null && r.Start <= request.Start && r.Start + r.Size > request.Start);
        Partitions.SelectedItem = released;
        InventoryStatus.Text = (isExample ? L("示例：已模拟删除，真实磁盘未改动。", "Example: deletion simulated; real disks unchanged.") : L("已删除选定分区。", "Selected partition deleted."))
            + (released != null ? L("已选中释放后的未分配空间，可继续设置安装容量。", "The released unallocated space is selected. Choose an installation capacity.")
                : L("释放后的连续空间仍不足 64 GiB，或磁盘不符合安装要求。请查看列表。", "Released contiguous space is still below 64 GiB, or this disk is ineligible. Review the list."));
    }
    private void UseAll(object sender, RoutedEventArgs e)
    { if (gap != null) CapacityInput.Text = (gap.Size / (decimal)PartitionInventory.GiB).ToString(CultureInfo.InvariantCulture); }
    private void UsePreset(object sender, RoutedEventArgs e)
    {
        if (gap != null && sender is Button { Tag: string value }
            && decimal.TryParse(value, CultureInfo.InvariantCulture, out var capacity)
            && capacity * PartitionInventory.GiB <= gap.Size) CapacityInput.Text = value;
    }
    private void CapacityChanged(object sender, TextChangedEventArgs e) { if (!updating && ChangesHost != null) UpdatePlan(); }
    private void PlacementChanged(object sender, RoutedEventArgs e) { if (!updating && ChangesHost != null) UpdatePlan(); }
    private void UpdatePlan()
    {
        if (updating) return;
        updating = true;
        FormatRemainingButton.IsEnabled = false;
        FormatRemainingButton.ToolTip = L("选择安装容量后，至少保留 64 MiB 余量才能创建 NTFS。", "Choose an installation capacity leaving at least 64 MiB for NTFS.");
        Capacity64Button.IsEnabled = gap?.Size >= 64 * PartitionInventory.GiB;
        Capacity100Button.IsEnabled = gap?.Size >= 100 * PartitionInventory.GiB;
        Capacity100Button.ToolTip = gap != null && gap.Size < 100 * PartitionInventory.GiB
            ? L("所选连续未分配空间不足 100 GiB。", "The selected unallocated region is smaller than 100 GiB.")
            : L("将安装容量设为 100 GiB。", "Set installation capacity to 100 GiB.");
        ChangesHost.Children.Clear();
        try
        {
            if (gap == null) return;
            var plan = Selection;
            FormatRemainingButton.IsEnabled = (example || AllowPhysicalDeletion) && gap.Size - plan.Capacity >= RemainingSpaceFormat.Minimum;
            if (!example && !AllowPhysicalDeletion) FormatRemainingButton.ToolTip = L("演练模式不会格式化真实磁盘。", "Rehearsal mode cannot format real disks.");
            else if (FormatRemainingButton.IsEnabled) FormatRemainingButton.ToolTip = L("核对范围并确认后立即创建 NTFS；已有分区保持不变。", "Review and confirm to create NTFS immediately; existing partitions are kept.");
            var after = PartitionInventory.After(plan); var home = after.Single(s => s.Name == "home" && s.Action == "new");
            CapacityHint.Foreground = new SolidColorBrush(Color.FromRgb(97,114,138));
            CapacityHint.Text = L($"已选择安装容量：{PartitionInventory.SizeText(plan.Capacity)} · 剩余未分配：{PartitionInventory.SizeText(gap.Size - plan.Capacity)}\n系统及启动约 24.375 GiB；数据分区 {PartitionInventory.SizeText(home.Size)}（格式化前）。\n可选范围：64–{gap.Size / (decimal)PartitionInventory.GiB:0.######} GiB。", $"Selected installation capacity: {PartitionInventory.SizeText(plan.Capacity)} · Unallocated remainder: {PartitionInventory.SizeText(gap.Size - plan.Capacity)}\nSystem and boot: about 24.375 GiB; data: {PartitionInventory.SizeText(home.Size)} (before formatting).\nAvailable range: 64–{gap.Size / (decimal)PartitionInventory.GiB:0.######} GiB.");
            ShowChanges(ChangesHost, plan);
        }
        catch (InvalidOperationException error) { CapacityHint.Text = error.Message; CapacityHint.Foreground = Brushes.Sienna; }
        finally { updating = false; Changed?.Invoke(); }
    }
    private async void FormatRemaining(object sender, RoutedEventArgs e)
    {
        if (busy || snapshot == null || gap == null || (!example && !AllowPhysicalDeletion)) return;
        RemainingFormatRequest request;
        try { request = new(Selection, InstallerI18n.Language); RemainingSpaceFormat.Plan(request.Selection); }
        catch (InvalidOperationException error) { InventoryStatus.Text = error.Message; return; }
        var owner = Window.GetWindow(this);
        if (example)
        {
            var dialog = RemainingSpaceFormat.Confirmation(request); dialog.Owner = owner; dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner;
            if (dialog.ShowDialog() == true) SelectReservedSpace(RemainingSpaceFormat.Simulate(request), true, request);
            return;
        }
        busy = true; gap = null; Changed?.Invoke();
        if (owner != null) owner.IsEnabled = false;
        FormatRemainingButton.IsEnabled = false;
        InventoryStatus.Text = L("请在管理员窗口核对剩余空间。完成后将重新读取磁盘…", "Review the remaining space in the administrator window. Disks will be refreshed afterward…");
        string? failure = null; bool formatted = false;
        try { formatted = await RemainingSpaceFormat.RunAsync(request); }
        catch (Exception error) { failure = error.Message; }
        Clear();
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            var fresh = await Backend.PowerShellAsync("read-disks.ps1", [], _ => { }, timeout.Token);
            busy = false;
            if (formatted) SelectReservedSpace(fresh, false, request); else LoadSnapshot(fresh, false);
            if (!formatted) InventoryStatus.Text = failure == null ? L("已取消格式化。磁盘列表已刷新，请重新选择安装空间和容量。", "Formatting cancelled. Disks refreshed; select the installation region and capacity again.")
                : L("格式化未确认完成，可能已创建分区。请核对刷新后的布局再继续：\n", "Formatting was not confirmed; a partition may have been created. Review the refreshed layout before continuing:\n") + failure;
        }
        catch (Exception error) { Clear(); InventoryStatus.Text = L("无法确认当前布局，请重新读取磁盘：\n", "Could not confirm the layout. Read disks again:\n") + failure + "\n" + error.Message; }
        finally { busy = false; if (owner != null) owner.IsEnabled = true; Changed?.Invoke(); }
    }

    internal void SelectReservedSpace(string json, bool isExample, RemainingFormatRequest request)
    {
        RemainingSpaceFormat.ValidateFormattedSnapshot(json, isExample, request);
        LoadSnapshot(json, isExample);
        Disks.SelectedItem = Disks.Items.Cast<InventoryDisk>().SingleOrDefault(d => d.Number == request.Selection.Disk);
        Partitions.SelectedItem = Partitions.Items.Cast<PartitionRow>().SingleOrDefault(r => r.Space?.Start == request.Selection.Target().Start);
        AlignRight.IsChecked = request.Selection.AlignRight;
        AlignLeft.IsChecked = !request.Selection.AlignRight;
        if (gap != null) CapacityInput.Text = (request.Selection.Capacity / (decimal)PartitionInventory.GiB).ToString(CultureInfo.InvariantCulture);
        InventoryStatus.Text = isExample ? L("示例：已模拟创建 NTFS，保留的 SteamOS 空间已选中。", "Example: NTFS creation simulated; reserved SteamOS space selected.")
            : L("NTFS 数据分区已创建。已刷新磁盘并选中保留的 SteamOS 空间。", "NTFS data partition created. Disks refreshed and reserved SteamOS space selected.");
    }

    public static void ShowChanges(StackPanel host, PartitionSelection plan)
    {
        host.Children.Clear(); var target = plan.Target();
        var disk = PartitionInventory.Read(plan.Snapshot).Single(d => d.Number == target.Disk);
        Text(L("安装前后 · 规划预览", "Before and after · planned layout"), true);
        Text((plan.Example ? L("示例 · ", "Example · ") : "") + disk.Title);
        var before = PartitionInventory.Before(disk); var after = PartitionInventory.After(plan);
        var remainder = disk.Rows.Single(r => r.Space?.Start == plan.Start).Size - plan.Capacity;
        Text(plan.AlignRight ? L("安装区靠右 · SteamOS 位于所选空间末端", "Right placement · SteamOS at the end of the selected region") : L("安装区靠左 · SteamOS 位于所选空间起点", "Left placement · SteamOS at the start of the selected region"));
        Text(L($"SteamOS：{PartitionInventory.SizeText(plan.Capacity)} · 此段剩余未分配：{PartitionInventory.SizeText(remainder)}", $"SteamOS: {PartitionInventory.SizeText(plan.Capacity)} · Unallocated remainder in this region: {PartitionInventory.SizeText(remainder)}"));
        Bar(L("安装前", "Before"), before); Bar(L("安装后（规划）", "After (planned)"), after);
        Text(L("蓝：保留分区　绿：新增 SteamOS　灰：未分配", "Blue: kept   Green: new SteamOS   Gray: unallocated"));
        Text(L("保留所有已有分区；新增 8 个 SteamOS 分区。", "Keep all existing partitions; add 8 SteamOS partitions."));
        var detail = new StackPanel();
        foreach (var s in after)
        {
            var action = s.Action == "new" ? L("新增", "New") : s.Action == "keep" ? L("保留", "Keep") : L("未分配", "Unallocated");
            detail.Children.Add(new TextBlock { Text = $"{action} · {s.Name} · {PartitionInventory.SizeText(s.Size)}", TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,4,0,4) });
        }
        host.Children.Add(new Expander { Header = L("查看分区变化明细", "Partition change details"), Content = detail, Margin = new Thickness(0,8,0,8) });
        void Text(string value, bool bold = false) => host.Children.Add(new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal, Margin = new Thickness(0,6,0,6) });
        void Bar(string title, LayoutSegment[] segments)
        {
            Text(title); var grid = new Grid { Height = 32, ClipToBounds = true };
            foreach (var s in segments)
            {
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(s.Size, GridUnitType.Star) });
                var label = $"{s.Name} · {PartitionInventory.SizeText(s.Size)}";
                var border = new Border { Background = new SolidColorBrush(s.Action == "new" ? Color.FromRgb(41,151,112) : s.Action == "keep" ? Color.FromRgb(68,116,185) : Color.FromRgb(204,213,225)), BorderBrush = Brushes.White, BorderThickness = new Thickness(0,0,1,0), ToolTip = label };
                AutomationProperties.SetName(border, label);
                Grid.SetColumn(border, grid.ColumnDefinitions.Count - 1); grid.Children.Add(border);
            }
            host.Children.Add(grid);
        }
    }
}
