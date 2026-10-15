using System.IO;
using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace OxpInstaller;

internal static class InstallationResultChecks
{
    internal static string Run(MainWindow window)
    {
        var directory = Path.Combine(Backend.Root, "logs", "installation-result-checks");
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        T Find<T>(string name) => (T)window.FindName(name);
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); checks.Add(name); }
        var show = typeof(MainWindow).GetMethod("ShowResult", BindingFlags.Instance | BindingFlags.NonPublic)!;
        Find<PartitionPicker>("PartitionSelector").AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        BootSetupChecks.Acknowledge(window);
        foreach (var language in new[] { "zh-CN", "en-US" })
        foreach (var makeDefault in new[] { false, true })
        foreach (var status in new[] { "awaiting-device-boot", "failed", "cancelled", "complete" })
        {
            InstallerI18n.SetLanguage(language);
            var physical = status != "complete";
            var state = new InstallationSession(1, Guid.NewGuid().ToString("N"), InstallationTargetKind.InternalShared,
                "fixture.img", true, status, status, null, status == "failed" ? "Fixture failure" : null, DateTime.UtcNow, Physical: physical, MakeDefaultBoot: physical && makeDefault);
            show.Invoke(window, [state]);
            var success = status is "awaiting-device-boot" or "complete";
            Require((Find<Border>("IncompleteCard").Visibility == Visibility.Collapsed) == success, language + "/" + status + "/completion-warning");
            Require((Find<StackPanel>("RestartPanel").Visibility == Visibility.Visible) == (success && physical), language + "/" + status + "/restart-eligibility");
            Require((((SolidColorBrush)Find<TextBlock>("NavResult").Foreground).Color == Color.FromRgb(134,239,172)) == success, language + "/" + status + "/navigation-color");
            if (status != "awaiting-device-boot") continue;
            Require(Find<TextBlock>("ResultScope").Text == MainWindow.BootResultGuidance(state), language + "/" + makeDefault + "/boot-guidance-matches-completed-task");
            var componentDirectory = InstallationController.SessionDirectory(state);
            Directory.CreateDirectory(componentDirectory);
            var componentReport = Path.Combine(componentDirectory, "components.json");
            try
            {
                var sharedStorageReport = JsonSerializer.Serialize(new[] { "A", "B" }.Select(slot => new
                {
                    slot, id = "shared-storage", status = "not_installed", safe_to_skip = true,
                    reason = "Unsafe shared storage path: fixture preflight conflict"
                }));
                File.WriteAllText(componentReport, sharedStorageReport);
                show.Invoke(window, [state]);
                Require(Find<TextBlock>("ResultScope").Text.Contains(language == "zh-CN" ? "共享分区挂载" : "Shared partition mounts"), language + "/shared-storage-summary-label");
                Require(!Find<TextBlock>("ResultScope").Text.Contains(language == "zh-CN" ? "系统更新" : "system update"), language + "/new-report-has-no-update-policy-summary");
                Require(Find<TextBlock>("ResultScope").Text.Contains("fixture preflight conflict"), language + "/shared-storage-warning-reason");
                Require(Find<TextBlock>("ResultMessage").Text.Contains(language == "zh-CN" ? "被跳过" : "were skipped"), language + "/shared-storage-warning-visible");
                Require(Find<StackPanel>("RestartPanel").Visibility == Visibility.Visible, language + "/shared-storage-skip-keeps-success");
                File.WriteAllText(componentReport, JsonSerializer.Serialize(new[] { "A", "B" }.Select(slot => new
                {
                    slot, id = "system-update-policy", status = "files_installed"
                })));
                show.Invoke(window, [state]);
                var historicalSummary = Find<TextBlock>("ResultScope").Text;
                Require(historicalSummary.Contains(language == "zh-CN" ? "历史系统更新策略" : "Historical system update policy")
                    && historicalSummary.Contains(language == "zh-CN" ? "此任务曾部署系统更新暂停策略" : "This task deployed a system update pause policy")
                    && historicalSummary.Contains(language == "zh-CN" ? "不代表当前系统的更新状态" : "does not describe the system's current update status"),
                    language + "/historical-update-policy-preserves-past-action-without-claiming-current-state");
                File.WriteAllText(componentReport, JsonSerializer.Serialize(new[] { "A", "B" }.Select(slot => new
                {
                    slot, id = "system-update-hold", status = "files_installed"
                })));
                show.Invoke(window, [state]);
                var holdSummary = Find<TextBlock>("ResultScope").Text;
                Require(holdSummary.Contains(language == "zh-CN" ? "保留当前系统版本" : "Preserve current system version")
                    && holdSummary.Contains(language == "zh-CN" ? "暂缓 SteamOS 系统更新" : "holds SteamOS system updates")
                    && holdSummary.Contains(language == "zh-CN" ? "Steam 客户端与游戏更新不受影响" : "Steam client and game updates are unaffected"),
                    language + "/update-hold-discloses-scope");
                File.WriteAllText(componentReport, sharedStorageReport);
                show.Invoke(window, [state]);
            }
            finally { File.Delete(componentReport); Directory.Delete(componentDirectory); }
            Require(Find<TextBlock>("ResultTitle").Text == (language == "zh-CN" ? "写入完成" : "Writing complete"), language + "/successful-write-title");
            Require(((SolidColorBrush)Find<Border>("ResultCard").Background).Color == Color.FromRgb(236,253,243), language + "/green-success-card");
            foreach (var size in new[] { new Size(850,620), new Size(1280,800) })
            {
                window.Width = size.Width; window.Height = size.Height;
                var root = (FrameworkElement)window.Content;
                root.Measure(size); root.Arrange(new Rect(size)); root.UpdateLayout();
                var button = Find<Button>("RestartButton");
                var point = button.TransformToAncestor(root).Transform(new Point());
                Require(point.X >= 0 && point.Y >= 0 && point.X + button.ActualWidth <= size.Width && point.Y + button.ActualHeight <= size.Height, language + "/" + size + "/restart-visible");
                var path = Path.Combine(directory, $"{language}-{size.Width}x{size.Height}");
                WizardChecks.ExportSvg(root, size, path + ".svg");
                var bitmap = new RenderTargetBitmap((int)size.Width, (int)size.Height, 96,96,PixelFormats.Pbgra32);
                bitmap.Render(root);
                var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
                using var file = File.Create(path + ".png"); encoder.Save(file);
            }
        }
        return JsonSerializer.Serialize(new { checks, directory, restartExecuted = false }, new JsonSerializerOptions { WriteIndented = true });
    }
}
