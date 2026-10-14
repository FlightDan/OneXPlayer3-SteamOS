using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public sealed record RemainingFormatRequest(PartitionSelection Selection, string Language);
public sealed record RemainingFormatPlan(int Disk, long Start, long Size);

public static class RemainingSpaceFormat
{
    private static string L(string zh, string en) => PartitionInventory.L(zh, en);
    public const long Minimum = 64 * PartitionInventory.MiB;
    internal static RemainingFormatPlan Plan(PartitionSelection selection)
    {
        var target = selection.Target();
        var gap = PartitionInventory.Read(selection.Snapshot).Single(d => d.Number == selection.Disk).Rows.Single(r => r.Space?.Start == selection.Start);
        var remainder = checked(gap.Size - target.Size);
        if (remainder < Minimum) throw new InvalidOperationException(L("剩余空间至少需要 64 MiB；使用全部空间时不能再创建 NTFS。", "At least 64 MiB must remain; using all space leaves no room for NTFS."));
        return new(target.Disk, checked(target.Start + target.Size), remainder);
    }

    internal static string Simulate(RemainingFormatRequest request)
    {
        if (!request.Selection.Example) throw new InvalidOperationException("Simulation requires an example.");
        var plan = Plan(request.Selection);
        var root = JsonNode.Parse(request.Selection.Snapshot)!.AsArray();
        var disk = root.Single(d => (int)d!["number"]! == plan.Disk)!;
        var parts = disk["partitions"]!.AsArray();
        parts.Add(JsonSerializer.SerializeToNode(new {
            number = parts.Select(p => (int)p!["number"]!).DefaultIfEmpty(0).Max() + 1, offset = plan.Start, size = plan.Size,
            guid = Guid.NewGuid().ToString(), gptType = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7",
            type = "Basic", filesystem = "NTFS", label = "Data", letter = "", free = plan.Size,
            isBoot = false, isSystem = false, isHidden = false, deletionAllowed = true
        }));
        return root.ToJsonString();
    }

    internal static Window Confirmation(RemainingFormatRequest request)
    {
        var plan = Plan(request.Selection);
        var disk = PartitionInventory.Read(request.Selection.Snapshot).Single(d => d.Number == plan.Disk);
        var window = new Window { Title = L("格式化剩余空间", "Format remaining space"), Width = 580, SizeToContent = SizeToContent.Height,
            MaxHeight = SystemParameters.WorkArea.Height, WindowStartupLocation = WindowStartupLocation.CenterScreen,
            ResizeMode = ResizeMode.NoResize, FontSize = 15, Background = Brushes.White, Foreground = new SolidColorBrush(Color.FromRgb(25,43,67)) };
        var panel = new StackPanel { Margin = new Thickness(24) };
        void Text(string value) => panel.Children.Add(new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,0,0,16) });
        Text(request.Selection.Example ? L("示例操作 · 不影响真实磁盘", "Example operation · no real disk changes") : disk.Title);
        Text(L($"保留 {PartitionInventory.SizeText(request.Selection.Capacity)} 未分配空间用于 SteamOS。\n将同一段空间的剩余 {PartitionInventory.SizeText(plan.Size)} 创建为 NTFS 数据分区。", $"Reserve {PartitionInventory.SizeText(request.Selection.Capacity)} of unallocated space for SteamOS.\nCreate an NTFS data partition using the remaining {PartitionInventory.SizeText(plan.Size)} in this region."));
        Text(L($"字节范围：{plan.Start}–{checked(plan.Start + plan.Size)}（不含末尾）\n1 MiB 对齐（兼容 4K） · 4096 字节簇 · 卷标 Data", $"Byte range: {plan.Start}–{checked(plan.Start + plan.Size)} (exclusive end)\n1 MiB alignment (4K aligned) · 4096-byte clusters · Label: Data"));
        Text(L("确认后立即创建并格式化，不等待安装。已有分区保持不变。若取消后续安装，此 NTFS 分区仍会保留。", "Creates and formats immediately, before installation. Existing partitions are kept. This NTFS partition remains even if installation is later cancelled."));
        var consent = new CheckBox { Name = "FormatConsent", Content = new TextBlock { Text = L("确认将上述剩余未分配空间创建为 NTFS。", "Create NTFS in the unallocated range shown above."), TextWrapping = TextWrapping.Wrap } };
        var actions = new WrapPanel { HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0,16,0,0) };
        var cancel = new Button { Content = L("取消", "Cancel"), IsCancel = true, IsDefault = true };
        var confirm = new Button { Name = "FormatConfirm", Content = request.Selection.Example ? L("模拟格式化", "Simulate format") : L("立即创建 NTFS", "Create NTFS now"), IsEnabled = false };
        consent.Checked += (_, _) => confirm.IsEnabled = true; consent.Unchecked += (_, _) => confirm.IsEnabled = false;
        confirm.Click += (_, _) => { if (consent.IsChecked == true) window.DialogResult = true; };
        panel.Children.Add(consent); actions.Children.Add(cancel); actions.Children.Add(confirm); panel.Children.Add(actions);
        window.Content = new ScrollViewer { Content = panel, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        window.Loaded += (_, _) => cancel.Focus();
        return window;
    }

    public static async Task<int> ExecuteHelperAsync(string path)
    {
        Application.Current.ShutdownMode = ShutdownMode.OnExplicitShutdown;
        path = Path.GetFullPath(path); MediaSource.Ordinary(path, InstallationController.Work);
        if (Path.GetFileName(path) != "format-request.json" || new FileInfo(path).Length > 4 * 1024 * 1024) throw new IOException("Invalid formatting request.");
        using var jobLock = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        var request = await JsonSerializer.DeserializeAsync<RemainingFormatRequest>(jobLock) ?? throw new IOException("Empty formatting request.");
        InstallerI18n.SetLanguage(request.Language);
        try
        {
            if (request.Selection.Example || !new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) throw new IOException("Real formatting requires administrator access.");
            Plan(request.Selection);
            await Backend.PowerShellAsync("format-remaining.ps1", ["-RequestPath", path, "-ValidateOnly"], _ => { }, CancellationToken.None);
            if (Confirmation(request).ShowDialog() != true) return 2;
            await Backend.PowerShellAsync("format-remaining.ps1", ["-RequestPath", path], _ => { }, CancellationToken.None);
            return 0;
        }
        catch (Exception error) { await File.WriteAllTextAsync(Path.Combine(Path.GetDirectoryName(path)!, "error.txt"), error.Message); return 1; }
    }

    internal static async Task<bool> RunAsync(RemainingFormatRequest request)
    {
        if (request.Selection.Example) throw new InvalidOperationException("Example requests cannot reach the physical helper.");
        Plan(request.Selection);
        var directory = Path.Combine(InstallationController.Work, "partition-format-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "format-request.json"); await File.WriteAllTextAsync(path, JsonSerializer.Serialize(request));
        var start = new ProcessStartInfo(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe")) { UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden };
        start.ArgumentList.Add(typeof(App).Assembly.Location); start.ArgumentList.Add("--format-remaining-helper"); start.ArgumentList.Add(path);
        try
        {
            using var process = Process.Start(start) ?? throw new IOException("Formatting helper did not start.");
            await process.WaitForExitAsync();
            if (process.ExitCode == 2) return false;
            if (process.ExitCode != 0) throw new IOException(File.Exists(Path.Combine(directory, "error.txt")) ? await File.ReadAllTextAsync(Path.Combine(directory, "error.txt")) : L("格式化未确认完成，请刷新磁盘核对。", "Formatting was not confirmed; refresh disks to check."));
            return true;
        }
        catch (Win32Exception error) when (error.NativeErrorCode == 1223) { return false; }
    }
}
