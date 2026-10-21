using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace OxpInstaller;

public partial class MainWindow
{
    private bool bootPrerequisitesAcknowledged;
    // Read-only firmware preflight; UI checks substitute synthetic states only.
    internal Action SecureBootPreflight { get; set; } = FirmwareBoot.RequireSecureBootDisabled;
    private bool secureBootChecked;
    private string? secureBootIssue;
    private const string BootPrerequisitesZh = "安装前，请先在 BIOS / UEFI 中关闭安全启动（Secure Boot），再返回 Windows 运行安装助手。当前 SteamOS / rEFInd 引导需要关闭安全启动。\n\n如果启用了 BitLocker 或 Windows 设备加密，关闭安全启动或更改启动顺序可能导致硬盘无法自动解锁，进入 Windows 时要求输入恢复密钥。没有恢复密钥时，可能无法访问加密数据。\n\n请先在 Windows 中备份并确认可用的 BitLocker 恢复密钥，再暂停 BitLocker 保护，之后进入 BIOS 关闭安全启动。安装完成并验证 Windows 正常启动后，恢复 BitLocker 保护。暂停保护期间数据保护会减弱，请勿长期保持暂停。\n\n尚未完成准备时，请退出安装助手。此提示不会替你修改 BIOS、暂停加密保护或收集恢复密钥。";
    private const string BootPrerequisitesEn = "Before installing, disable Secure Boot in BIOS / UEFI, then return to Windows and run the installer. The current SteamOS / rEFInd loader requires Secure Boot to be off.\n\nIf BitLocker or Windows Device Encryption is enabled, disabling Secure Boot or changing the boot order may prevent automatic drive unlocking. Windows may ask for the recovery key. Without it, encrypted data may be inaccessible.\n\nFirst back up and verify your BitLocker recovery key in Windows, then suspend BitLocker protection before disabling Secure Boot in BIOS. Resume protection after installation and successful Windows boot verification. Suspension weakens data protection; do not leave it suspended indefinitely.\n\nExit the installer if you are not ready. This notice does not change BIOS settings, suspend protection or collect recovery keys.";

    private void RefreshBootPrerequisites()
    {
        BootPrerequisitesTitle.Text = PartitionInventory.L("安装前：关闭安全启动，准备恢复密钥", "Before installing: Secure Boot and recovery key");
        var message = PartitionInventory.L(BootPrerequisitesZh, BootPrerequisitesEn);
        var instruction = PartitionInventory.L("安装前，请先在 BIOS / UEFI 中关闭安全启动", "Before installing, disable Secure Boot in BIOS / UEFI");
        var warning = PartitionInventory.L("关闭安全启动或更改启动顺序可能导致硬盘无法自动解锁", "disabling Secure Boot or changing the boot order may prevent automatic drive unlocking");
        var warningStart = message.IndexOf(warning, StringComparison.Ordinal);
        BootPrerequisitesMessage.Inlines.Clear();
        BootPrerequisitesMessage.Inlines.Add(new Run(instruction) { FontWeight = FontWeights.Bold, TextDecorations = TextDecorations.Underline });
        BootPrerequisitesMessage.Inlines.Add(new Run(message[instruction.Length..warningStart]));
        BootPrerequisitesMessage.Inlines.Add(new Run(warning) { FontWeight = FontWeights.Bold, TextDecorations = TextDecorations.Underline });
        BootPrerequisitesMessage.Inlines.Add(new Run(message[(warningStart + warning.Length)..]));
        BootPrerequisitesConsent.Content = new TextBlock { TextWrapping = TextWrapping.Wrap, Text = PartitionInventory.L("我已关闭安全启动；如启用加密，已保存恢复密钥并暂停保护", "Secure Boot is off; if encryption is enabled, I have saved the recovery key and suspended protection") };
        BootPrerequisitesExit.Content = PartitionInventory.L("退出，先做准备", "Exit to prepare");
        BootPrerequisitesContinue.Content = PartitionInventory.L("进入安装位置", "Choose installation location");
        BootPrerequisitesNote.Text = PartitionInventory.L("安装前关闭 BIOS / UEFI 安全启动；BitLocker / 设备加密可能无法自动解锁，请先保存恢复密钥并暂停保护。", "Disable Secure Boot before installation. BitLocker / Device Encryption may require a recovery key; save it and suspend protection first.");
        BootPrerequisitesShow.Content = PartitionInventory.L("查看安装前准备提示", "Review boot prerequisites");
        RefreshSecureBootStatus();
    }
    private void RefreshSecureBootStatus()
    {
        BootPrerequisitesStatus.Text = !secureBootChecked ? "" : secureBootIssue == null
            ? PartitionInventory.L("检测结果：安全启动已关闭。", "Detected: Secure Boot is disabled.")
            : PartitionInventory.L("无法继续：", "Cannot continue: ") + secureBootIssue;
        BootPrerequisitesStatus.Foreground = secureBootIssue == null ? Brushes.DarkGreen : Brushes.DarkRed;
    }
    private bool CheckSecureBootPrerequisite()
    {
        secureBootChecked = true;
        try { SecureBootPreflight(); secureBootIssue = null; }
        catch (Exception error)
        {
            secureBootIssue = PartitionInventory.L("未能确认安全启动已关闭。请关闭后重试，或检查管理员权限。", "Secure Boot could not be confirmed disabled. Disable it and retry, or check administrator permissions.") + "\n" + error.Message;
            bootPrerequisitesAcknowledged = false;
            PartitionSelector.BootPrerequisitesReady = false;
        }
        RefreshSecureBootStatus();
        return secureBootIssue == null;
    }
    private void ShowBootPrerequisites(object? sender, RoutedEventArgs? e)
    {
        bootPrerequisitesAcknowledged = false;
        PartitionSelector.BootPrerequisitesReady = false;
        BootPrerequisitesConsent.IsChecked = false;
        RefreshBootPrerequisites();
        WizardShell.IsEnabled = false;
        BootPrerequisitesOverlay.Visibility = Visibility.Visible;
        CheckSecureBootPrerequisite();
        BootPrerequisitesExit.Focus();
    }
    private void BootPrerequisitesConsentChanged(object sender, RoutedEventArgs e)
    {
        if (BootPrerequisitesContinue != null) BootPrerequisitesContinue.IsEnabled = BootPrerequisitesConsent.IsChecked == true;
    }
    private async void ConfirmBootPrerequisites(object sender, RoutedEventArgs e)
    {
        if (BootPrerequisitesConsent.IsChecked != true) return;
        // Re-read at dismissal: neither the checkbox nor a cached state grants entry.
        if (!CheckSecureBootPrerequisite()) { BootPrerequisitesStatus.BringIntoView(); return; }
        bootPrerequisitesAcknowledged = true;
        BootPrerequisitesOverlay.Visibility = Visibility.Collapsed;
        WizardShell.IsEnabled = true;
        PartitionSelector.BootPrerequisitesReady = true;
        UpdateNavigationState();
        NextButton.Focus();
        await PartitionSelector.ReadDisksOnOpenAsync();
    }
    private void ExitBootPrerequisites(object sender, RoutedEventArgs e) => Close();
}
