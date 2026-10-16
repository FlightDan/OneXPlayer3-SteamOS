using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

internal sealed class SharedStoragePanel : StackPanel
{
    private readonly TextBlock heading = new() { FontSize = 19, FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap, Margin = new(0, 0, 0, 10) };
    private readonly TextBlock introduction = Note();
    private readonly TextBlock status = Note();
    private readonly TextBlock details = Note();
    private readonly StackPanel choices = new();
    private readonly Dictionary<string, (StorageCandidate Candidate, CheckBox Box)> boxes = new();
    private string? snapshot;
    private bool example;
    private bool refreshing;
    internal event Action? Changed;
    internal event Action? ReturnToDisks;
    internal Button SkipButton { get; } = new() { Name = "SkipSharedStorage", Margin = new(0, 10, 12, 0) };
    internal Button DiskButton { get; } = new() { Margin = new(0, 10, 0, 0) };
    internal IReadOnlyDictionary<string, (StorageCandidate Candidate, CheckBox Box)> Choices => boxes;
    internal StorageMount[] Selection => boxes.Values.Where(value => value.Box.IsChecked == true).Select(value => value.Candidate.Mount).ToArray();
    internal SharedStoragePanel()
    {
        Children.Add(heading); Children.Add(introduction); Children.Add(status); Children.Add(choices); Children.Add(details);
        var actions = new WrapPanel(); actions.Children.Add(SkipButton); actions.Children.Add(DiskButton); Children.Add(actions);
        DiskButton.Click += (_, _) => ReturnToDisks?.Invoke();
        RefreshLanguage();
    }
    private static TextBlock Note() => new() { TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Color.FromRgb(97, 114, 138)), LineHeight = 23, Margin = new(0, 0, 0, 12) };
    internal void LoadSnapshot(string? value, bool isExample)
    {
        if (snapshot == value && example == isExample) return;
        var candidates = SharedStorage.Candidates(value);
        var selected = boxes.Values.Where(entry => entry.Box.IsChecked == true && example == isExample
            && candidates.Any(current => current.Mount == entry.Candidate.Mount
                && current.DiskGuid == entry.Candidate.DiskGuid && current.Serial == entry.Candidate.Serial
                && current.DiskSize == entry.Candidate.DiskSize && current.Start == entry.Candidate.Start
                && current.Size == entry.Candidate.Size)).Select(entry => entry.Candidate.Mount).ToArray();
        snapshot = value; example = isExample;
        Render(selected);
        Changed?.Invoke();
    }
    private void Render(StorageMount[] selected)
    {
        refreshing = true;
        try
        {
            boxes.Clear(); choices.Children.Clear();
            foreach (var candidate in SharedStorage.Candidates(snapshot))
            {
                var content = new StackPanel();
                content.Children.Add(new TextBlock { Text = candidate.Title, TextWrapping = TextWrapping.Wrap, FontWeight = FontWeights.SemiBold });
                content.Children.Add(new TextBlock { Text = SharedStorage.MountPath(candidate.Mount), TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Color.FromRgb(97, 114, 138)), Margin = new(0, 4, 0, 0) });
                var box = new CheckBox { Content = content, IsChecked = selected.Contains(candidate.Mount), HorizontalContentAlignment = HorizontalAlignment.Stretch, Margin = new(0, 0, 0, 12), MinHeight = 48 };
                System.Windows.Automation.AutomationProperties.SetName(box, candidate.Title);
                box.Checked += SelectionChanged; box.Unchecked += SelectionChanged;
                choices.Children.Add(box); boxes.Add(candidate.Mount.Partuuid, (candidate, box));
            }
        }
        finally { refreshing = false; }
        UpdateStatus();
    }
    private void SelectionChanged(object sender, RoutedEventArgs e) { if (refreshing) return; UpdateStatus(); Changed?.Invoke(); }
    internal void ClearSelection()
    {
        foreach (var entry in boxes.Values) entry.Box.IsChecked = false;
        UpdateStatus();
    }
    private void UpdateStatus()
    {
        status.Text = boxes.Count == 0
            ? PartitionInventory.L("没有可选的数据分区。可在“安装位置”创建 NTFS 共享分区并刷新磁盘，或直接跳过。", "No eligible data partitions. Create an NTFS shared partition and refresh disks at Installation location, or skip this step.")
            : Selection.Length == 0 ? PartitionInventory.L("尚未选择分区，可以跳过。", "No partitions selected. You can skip this step.")
            : PartitionInventory.L($"已选择 {Selection.Length} 个分区。", $"{Selection.Length} partition(s) selected.");
        if (example) status.Text = PartitionInventory.L("示例布局 · 非实际设备\n", "Example layout · not a real device\n") + status.Text;
    }
    internal void RefreshLanguage()
    {
        heading.Text = PartitionInventory.L("挂载分区到 SteamOS", "Mount partitions in SteamOS");
        introduction.Text = PartitionInventory.L("选择要在 SteamOS 中访问的数据分区。安装后按需自动挂载，可在文件管理器中打开；不会自动添加 Steam 游戏库。", "Choose data partitions to access in SteamOS. They will mount on demand after installation and can be opened in the file manager. No Steam game library is added.");
        details.Text = PartitionInventory.L("此步骤可直接跳过。支持 GPT 磁盘和 SD 卡上的 NTFS、exFAT、FAT32、ext4 和单设备 Btrfs 数据分区。Linux 格式通过只读签名识别，保留原有文件权限并允许执行，可手动添加 Steam 游戏库；NTFS、exFAT、FAT32 仅用于文件共享，禁止直接执行文件。系统、启动、恢复和加密分区不在列表中。缺盘时可正常启动；Windows 未完全关闭的分区可能无法挂载。", "You can skip this step. Supports NTFS, exFAT, FAT32, ext4 and single-device Btrfs data partitions on GPT disks and SD cards. Linux formats are identified by read-only signatures, retain existing file permissions and allow execution; Steam libraries can be added manually. NTFS, exFAT and FAT32 are file shares with direct execution disabled. System, boot, recovery and encrypted partitions are excluded. Missing disks do not block startup; volumes left open by Windows may be unavailable.");
        SkipButton.Content = PartitionInventory.L("跳过，不挂载分区", "Skip without mounting partitions");
        DiskButton.Content = PartitionInventory.L("返回安装位置", "Back to installation location");
        Render(Selection);
    }
    internal string Describe() => Selection.Length == 0 ? PartitionInventory.L("共享分区：跳过", "Shared partitions: skipped")
        : PartitionInventory.L("共享分区：\n", "Shared partitions:\n") + string.Join("\n", boxes.Values.Where(v => v.Box.IsChecked == true).Select(v => v.Candidate.Title + " → " + SharedStorage.MountPath(v.Candidate.Mount)));
}
