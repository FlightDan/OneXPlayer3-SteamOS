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
            var state = new InstallationSession(1, new string('0', 32), InstallationTargetKind.InternalShared,
                "fixture.img", true, status, status, null, status == "failed" ? "Fixture failure" : null, DateTime.UtcNow, Physical: physical, MakeDefaultBoot: physical && makeDefault);
            show.Invoke(window, [state]);
            var success = status is "awaiting-device-boot" or "complete";
            Require((Find<Border>("IncompleteCard").Visibility == Visibility.Collapsed) == success, language + "/" + status + "/completion-warning");
            Require((Find<StackPanel>("RestartPanel").Visibility == Visibility.Visible) == (success && physical), language + "/" + status + "/restart-eligibility");
            Require((((SolidColorBrush)Find<TextBlock>("NavResult").Foreground).Color == Color.FromRgb(134,239,172)) == success, language + "/" + status + "/navigation-color");
            if (status != "awaiting-device-boot") continue;
            Require(Find<TextBlock>("ResultScope").Text == MainWindow.BootResultGuidance(state), language + "/" + makeDefault + "/boot-guidance-matches-completed-task");
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
