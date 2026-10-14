using System.IO;
using System.Windows;

namespace OxpInstaller;

public partial class MainWindow
{
    internal static string BootResultGuidance(InstallationSession state)
    {
        var guidance = state.Kind == InstallationTargetKind.InternalShared && state.MakeDefaultBoot
        ? PartitionInventory.L("已将 SteamOS (OXP3) 设为固件默认启动项。重启后进入启动管理器；如安装了 rEFInd，请在菜单选择系统。进入 Windows 时如要求 BitLocker 恢复密钥，请使用安装前保存的密钥。验证 Windows 正常启动后恢复 BitLocker 保护。", "SteamOS (OXP3) is now the default firmware boot entry. Restart to open the boot manager; if rEFInd is installed, select a system in its menu. Use your saved recovery key if Windows requests BitLocker recovery. Resume BitLocker protection after verifying Windows boots successfully.")
        : PartitionInventory.L("固件默认启动顺序未改变，重启可能仍进入 Windows。请在设备 UEFI 启动菜单中选择 SteamOS (OXP3) 或外部安装盘。Windows 可能要求 BitLocker 恢复密钥；验证正常启动后恢复保护。", "The firmware boot order is unchanged and restart may still boot Windows. Select SteamOS (OXP3) or the external installation disk in the UEFI boot menu. Windows may request the BitLocker recovery key; resume protection after successful boot verification.");
        if (state.DesktopRebootScript != null)
            guidance += "\n" + PartitionInventory.L("已创建桌面重启脚本：", "Desktop restart script created: ") + state.DesktopRebootScript;
        if (state.DesktopRebootWarning != null)
            guidance += "\n" + PartitionInventory.L("系统写入已完成，但桌面重启脚本未创建：", "System writing completed, but the desktop restart script could not be created: ") + state.DesktopRebootWarning;
        return guidance;
    }
    private async void RestartToSteamOS(object sender, RoutedEventArgs e)
    {
        if (operation != null || DownloadsBusy || session is not { Physical: true, Status: "awaiting-device-boot" or "complete" }) return;
        var defaultBoot = session.Kind == InstallationTargetKind.InternalShared && session.MakeDefaultBoot;
        if (MessageBox.Show(this,
            defaultBoot ? PartitionInventory.L("已设置默认启动项。请先保存其他程序中的工作；重启后进入 SteamOS / rEFInd。现在重启？", "The default boot entry is set. Save your work first; restart will boot SteamOS / rEFInd. Restart now?")
                : PartitionInventory.L("即将重启当前电脑并进入固件设置。请先保存其他程序中的工作，然后在启动菜单中选择 SteamOS 或安装目标设备。现在重启？", "This PC will restart into firmware settings. Save your work first, then select SteamOS or the installation device in the boot menu. Restart now?"),
            PartitionInventory.L("重启到 SteamOS", "Restart to SteamOS"), MessageBoxButton.OKCancel, MessageBoxImage.Question,
            MessageBoxResult.Cancel) != MessageBoxResult.OK) return;
        RestartButton.IsEnabled = false;
        string? restartLog = null;
        try
        {
            var directory = InstallationController.SessionDirectory(session);
            MediaSource.Ordinary(directory, InstallationController.Work, false);
            restartLog = Path.Combine(directory, "restart-" + Guid.NewGuid().ToString("N") + ".jsonl");
            await InstallerRestart.RunAsync(InstallerRestart.StartInfo(defaultBoot), restartLog);
        }
        catch (Exception error)
        {
            ValidationMessage.Text = PartitionInventory.L("写入已完成，但未能重启：", "Writing completed, but restart failed: ") + error.Message;
            if (restartLog != null) ValidationMessage.Text += "\n" + PartitionInventory.L("诊断日志：", "Diagnostic log: ") + restartLog;
        }
        finally { UpdateNavigationState(); }
    }
}
