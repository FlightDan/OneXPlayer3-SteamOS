using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

// Installed on the new SteamOS ESP; the existing firmware registration points to its fallback loader.
public sealed class BootOptionsPanel : StackPanel
{
    internal CheckBox InstallChoice { get; } = new() { IsChecked = true };
    internal CheckBox MakeDefaultChoice { get; } = new() { IsChecked = true };
    private readonly TextBlock firmwareNote = new() { TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Color.FromRgb(97, 114, 138)), Margin = new Thickness(0, 4, 0, 12), LineHeight = 22 };
    private bool firmwareAvailable;
    internal bool MakeDefaultBoot => firmwareAvailable && MakeDefaultChoice.IsChecked == true;
    internal RadioButton SteamOsChoice { get; } = new() { GroupName = "BootDefault", IsChecked = true };
    internal RadioButton WindowsChoice { get; } = new() { GroupName = "BootDefault" };
    internal RadioButton ForeverChoice { get; } = new() { GroupName = "BootWait" };
    internal RadioButton TimedChoice { get; } = new() { GroupName = "BootWait", IsChecked = true };
    internal TextBox Seconds { get; } = new() { Text = "2", Width = 96, MinHeight = 64, FontSize = 22, HorizontalContentAlignment = HorizontalAlignment.Center, VerticalContentAlignment = VerticalAlignment.Center };
    internal Button Minus { get; } = new() { Content = "−", Width = 64, MinHeight = 64, Padding = new Thickness(0), Margin = new Thickness(0, 0, 12, 0), FontSize = 28 };
    internal Button Plus { get; } = new() { Content = "+", Width = 64, MinHeight = 64, Padding = new Thickness(0), Margin = new Thickness(12, 0, 0, 0), FontSize = 28 };
    private readonly StackPanel settings = new();
    private readonly StackPanel timer = new() { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 12, 0, 12) };
    private readonly TextBlock error = new() { Foreground = Brushes.Firebrick, TextWrapping = TextWrapping.Wrap };
    private readonly List<(TextBlock Block, string Zh, string En)> labels = new();
    private bool ready;
    public BootOptionsPanel()
    {
        foreach (var choice in new[] { SteamOsChoice, WindowsChoice, ForeverChoice, TimedChoice })
            choice.SetResourceReference(FrameworkElement.StyleProperty, "TouchChoice");
        Children.Add(Label("BIOS / UEFI 启动顺序", "BIOS / UEFI boot order", true));
        Children.Add(MakeDefaultChoice);
        Children.Add(firmwareNote);
        Children.Add(InstallChoice);
        Children.Add(Label("安装到新建的 SteamOS EFI 分区，并备份原启动文件。", "Installs on the new SteamOS EFI partition and backs up its original loader."));
        Children.Add(settings);
        settings.Children.Add(Label("rEFInd 菜单默认系统", "Default system in the rEFInd menu", true));
        settings.Children.Add(Pair(SteamOsChoice, WindowsChoice));
        settings.Children.Add(Label("菜单等待", "Menu timeout", true));
        settings.Children.Add(Pair(ForeverChoice, TimedChoice));
        timer.Children.Add(Minus); timer.Children.Add(Seconds); timer.Children.Add(Plus);
        var unit = Label("秒", "seconds"); unit.Margin = new Thickness(12, 0, 0, 0); unit.VerticalAlignment = VerticalAlignment.Center;
        timer.Children.Add(unit); settings.Children.Add(timer);
        settings.Children.Add(error);
        settings.Children.Add(Label("勾选安装后随系统写入生效；Windows 入口按 EFI 分区识别。启动菜单使用手柄十字键或左摇杆选择，A / Start 确认，B 返回；OXP3 开机手柄支持待实机验证，也可用键盘。", "When selected, these settings are applied with the system. Windows uses its identified EFI partition. Use the D-pad or left stick to select, A / Start to confirm, B to return. OXP3 controller input at boot awaits device verification; keyboard input is also available."));
        InstallChoice.Checked += (_, _) => Update(); InstallChoice.Unchecked += (_, _) => Update();
        foreach (var radio in new[] { SteamOsChoice, WindowsChoice, ForeverChoice, TimedChoice }) radio.Checked += (_, _) => Update();
        Seconds.TextChanged += (_, _) => Update();
        Minus.Click += (_, _) => Adjust(-1); Plus.Click += (_, _) => Adjust(1);
        ready = true; Refresh();
    }
    internal void SetFirmwareContext(bool available)
    {
        firmwareAvailable = available;
        MakeDefaultChoice.IsEnabled = available;
        RefreshFirmwareNote();
    }
    private void RefreshFirmwareNote() => firmwareNote.Text = !firmwareAvailable
        ? PartitionInventory.L("外部盘安装或虚拟盘演练不修改当前电脑的默认启动项。请在目标设备的 UEFI 启动菜单中选择安装盘。", "External installation and rehearsal keep this PC's boot order. Select the installation disk in the target device's UEFI boot menu.")
        : PartitionInventory.L("默认勾选。安装完成后将 SteamOS (OXP3) 排到固件启动列表首位；安装 rEFInd 时重启先进入其菜单，否则直接进入 SteamOS。取消勾选则保留原顺序，可能仍先进入 Windows。原启动顺序会备份，Windows Boot Manager 保留。更改启动顺序可能触发 BitLocker 恢复，请提前保存恢复密钥并暂停保护。", "Selected by default. After installation, SteamOS (OXP3) becomes the first firmware boot entry. With rEFInd installed, restart opens its menu; otherwise it boots SteamOS directly. Uncheck to keep the original order, which may boot Windows first. The original order is backed up and Windows Boot Manager is retained. Boot order changes may trigger BitLocker recovery; save the recovery key and suspend protection first.");
    private TextBlock Label(string zh, string en, bool heading = false)
    {
        var label = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = heading ? new SolidColorBrush(Color.FromRgb(25, 43, 67)) : Brushes.SlateGray,
            FontWeight = heading ? FontWeights.SemiBold : FontWeights.Normal, FontSize = heading ? 16 : 14, Margin = new Thickness(0, heading ? 20 : 4, 0, 10), LineHeight = 22 };
        labels.Add((label, zh, en)); return label;
    }
    private static Grid Pair(UIElement first, UIElement second)
    {
        var grid = new Grid(); grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition());
        ((FrameworkElement)first).Margin = new Thickness(0, 0, 6, 0); ((FrameworkElement)second).Margin = new Thickness(6, 0, 0, 0);
        grid.Children.Add(first); Grid.SetColumn(second, 1); grid.Children.Add(second); return grid;
    }
    private void Adjust(int delta)
    {
        var value = int.TryParse(Seconds.Text, out var parsed) ? parsed : 2;
        Seconds.Text = Math.Clamp((long)value + delta, 1, 3600).ToString(CultureInfo.InvariantCulture);
    }
    internal string Configuration()
    {
        var seconds = 0;
        if (ForeverChoice.IsChecked != true && (!int.TryParse(Seconds.Text, out seconds) || seconds is < 1 or > 3600))
            throw new InvalidOperationException(PartitionInventory.L("等待时间请填写 1–3600 秒，或选择一直等待。", "Enter 1–3600 seconds, or choose Wait for selection."));
        var system = WindowsChoice.IsChecked == true ? "Windows" : "SteamOS";
        return $"# Settings only; merge into target-specific refind.conf.\n# Menu entries must be named Windows and SteamOS.\n# Requires bundled UsbXbox360Dxe driver and EFI/Xbox360/config.ini.\ndefault_selection \"{system}\"\ntimeout {seconds}\nscan_driver_dirs /EFI/OXP3-rEFInd/drivers_x64\nbig_icon_size 256\nsmall_icon_size 96\n";
    }
    internal void WriteConfiguration(string path) => File.WriteAllText(path, Configuration());
    internal RefindChoice? Selection
    {
        get
        {
            if (InstallChoice.IsChecked != true) return null;
            _ = Configuration();
            return new(WindowsChoice.IsChecked == true ? "Windows" : "SteamOS", ForeverChoice.IsChecked == true ? 0 : int.Parse(Seconds.Text));
        }
    }
    private void Update()
    {
        if (!ready) return;
        settings.Visibility = InstallChoice.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
        timer.IsEnabled = TimedChoice.IsChecked == true;
        try { _ = Configuration(); error.Text = ""; }
        catch (InvalidOperationException failure) { error.Text = failure.Message; }
    }
    public void Refresh()
    {
        InstallChoice.Content = new TextBlock { Text = PartitionInventory.L("安装 rEFInd 双系统启动菜单", "Install rEFInd dual-boot menu"), TextWrapping = TextWrapping.Wrap };
        MakeDefaultChoice.Content = new TextBlock { Text = PartitionInventory.L("将启动管理器设为默认启动项（推荐）", "Make the boot manager the default boot entry (recommended)"), TextWrapping = TextWrapping.Wrap };
        RefreshFirmwareNote();
        SteamOsChoice.Content = "SteamOS"; WindowsChoice.Content = "Windows";
        ForeverChoice.Content = new TextBlock { Text = PartitionInventory.L("一直等待选择", "Wait for selection"), TextWrapping = TextWrapping.Wrap };
        TimedChoice.Content = new TextBlock { Text = PartitionInventory.L("等待指定秒数", "Timed countdown"), TextWrapping = TextWrapping.Wrap };
        System.Windows.Automation.AutomationProperties.SetName(Minus, PartitionInventory.L("减少等待秒数", "Decrease timeout"));
        System.Windows.Automation.AutomationProperties.SetName(Plus, PartitionInventory.L("增加等待秒数", "Increase timeout"));
        System.Windows.Automation.AutomationProperties.SetName(Seconds, PartitionInventory.L("等待秒数", "Timeout in seconds"));
        foreach (var (block, zh, en) in labels) block.Text = PartitionInventory.L(zh, en);
        Update();
    }
}
