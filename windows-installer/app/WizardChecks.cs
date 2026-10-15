using System.Globalization;
using System.IO;
using System.Security;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;
public static class WizardChecks
{
    // Exercise physical-mode validation using a synthetic inventory only.
    // Stop at BootPage: never click its install button or invoke a disk writer.
    internal static string RunPhysicalNavigation(MainWindow window, string prepared)
    {
        var checks = new List<string>();
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        void Require(bool value, string name) { if (!value) throw new IOException(name + ": " + Find<TextBlock>("ValidationMessage").Text); checks.Add(name); }
        var picker = Find<PartitionPicker>("PartitionSelector"); picker.AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show(); BootSetupChecks.Acknowledge(window);
        foreach (var language in new[] { "ChineseLanguage", "EnglishLanguage" })
        {
            Find<RadioButton>(language).IsChecked = true;
            Click("TargetTab");
            picker.LoadSnapshot(PartitionInventory.ExampleJson, false);
            picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().First(r => r.Space != null);
            picker.CapacityInput.Text = "64";
            Click("NextButton");
            Require(Find<Grid>("SafetyOverlay").IsVisible, "target-consent-required-" + language);
            Click("SafetyContinue");
            Find<CheckBox>("UsePrepared").IsChecked = true; Find<TextBox>("ImagePath").Text = prepared;
            Click("NextButton");
            Require(Find<StackPanel>("ContentPage").IsVisible, "physical-source-advances-to-contents-" + language);
            Click("NextButton");
            Require(Find<StackPanel>("ReviewPage").IsVisible && window.CurrentOptions.StorageMounts == null, "physical-contents-to-review-without-mounts-" + language);
            Find<CheckBox>("PhysicalConsent").IsChecked = true; Click("NextButton");
            Require(Find<StackPanel>("BootPage").IsVisible && window.CompletedSession == null, "physical-review-advances-to-boot-without-writing-" + language);
            Click("BackButton"); Click("BackButton");
            Require(Find<StackPanel>("ContentPage").IsVisible, "physical-back-skips-mount-page-" + language);
        }
        return JsonSerializer.Serialize(new { passed = true, checks, physical_disk_writes = false }, new JsonSerializerOptions { WriteIndented = true });
    }

    public static string Run(MainWindow window, string prepared)
    {
        var directory = Path.Combine(Backend.Root, "logs", "wizard-ui-" + DateTime.Now.ToString("yyyyMMdd-HHmmss")); Directory.CreateDirectory(directory);
        var events = new List<string>();
        T Find<T>(string name) => (T)window.FindName(name);
        void Require(bool value, string message) { if (!value) throw new IOException(message); events.Add(message); }
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        ((PartitionPicker)window.FindName("PartitionSelector")).AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        events.AddRange(CheckFreeNavigation(window));
        var picker = Find<PartitionPicker>("PartitionSelector");
        picker.LoadSnapshot(PartitionInventory.ExampleJson, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().First(r => r.Space != null);
        var resumable = InstallationController.CanResume(InstallationController.Latest());
        Require(Find<Button>("ResumeRecentButton").Visibility == (resumable ? Visibility.Visible : Visibility.Collapsed), "resume-entry-matches-persisted-task-eligibility");
        Click("NextButton"); Find<TextBox>("ImagePath").Text = ""; Click("NextButton");
        Require(Find<StackPanel>("SourcePage").Visibility == Visibility.Visible && Find<TextBlock>("ValidationMessage").Text.Length > 0, "empty-source-stays-on-source-with-inline-error");
        var options = (InstallerOptionsPanel)Find<StackPanel>("ComponentOptionsHost").Children[0];
        options.OptionBoxes["decky"].IsChecked = false;
        Find<CheckBox>("UsePrepared").IsChecked = true; Find<TextBox>("ImagePath").Text = prepared; Click("NextButton");
        Require(Find<StackPanel>("ContentPage").Visibility == Visibility.Visible, "source-advance-does-not-validate-component-choices: " + Find<TextBlock>("ValidationMessage").Text);
        Require(!Find<CheckBox>("Upgrade310").IsEnabled && Find<TextBlock>("SystemVersionNote").Text.Contains("不再替换版本"), "prepared-image-does-not-promise-version-replacement");
        Click("NextButton");
        Require(Find<StackPanel>("ContentPage").IsVisible && Find<TextBlock>("ValidationMessage").Text.Length > 0, "dependency-error-belongs-to-contents-page");
        options.OptionBoxes["decky"].IsChecked = true; Click("NextButton");
        Require(Find<StackPanel>("ReviewPage").IsVisible, "contents-advance-directly-to-review");
        Click("NextButton");
        Require(Find<StackPanel>("BootPage").IsVisible && window.CompletedSession == null, "review-advances-to-boot-options-without-installing: " + Find<TextBlock>("ValidationMessage").Text);
        Click("BackButton");
        Require(((SolidColorBrush)Find<TextBlock>("NavSource").Foreground).Color != Color.FromRgb(255, 139, 139), "configured-source-clears-red-status");
        Click("BackButton"); Require(Find<TextBox>("ImagePath").Text == prepared, "back-retains-reviewed-source");
        Click("TargetTab"); Find<RadioButton>("ExternalTarget").IsChecked = true; Click("NextButton"); Click("NextButton"); Click("NextButton"); Click("NextButton");
        Require(Find<TextBlock>("ReviewTarget").Text.Contains("外部完整系统") && Find<TextBlock>("ReviewLayout").Text.Contains("清空"), "external-review-describes-full-system-and-erase-semantics");
        Click("SourceTab"); Find<CheckBox>("UsePrepared").IsChecked = false;
        Require(Find<TextBox>("ImagePath").Text.Length == 0, "source-kind-change-invalidates-old-path");
        Find<TextBox>("ImagePath").Text = "示例系统镜像.img";
        Find<CheckBox>("Upgrade310").IsChecked = false;
        Require(Find<TextBlock>("SystemVersionNote").Text.Contains("保留恢复镜像"), "unchecked-upgrade-keeps-source-version");
        Find<CheckBox>("Upgrade310").IsChecked = true;
        var layouts = new List<object>();
        foreach (var size in new[] { new Size(1060, 790), new Size(850, 620), new Size(1280, 800) })
        foreach (var step in Enumerable.Range(0, 8))
        {
            window.Width = size.Width; window.Height = size.Height; window.UpdateLayout();
            window.PreviewStep(step); var root = (FrameworkElement)window.Content;
            root.Measure(size); root.Arrange(new Rect(size)); root.UpdateLayout();
            var next = Find<Button>(step == 5 ? "StopButton" : "NextButton"); var point = next.TransformToAncestor(root).Transform(new Point());
            Require(point.X >= 0 && point.Y >= 0 && point.X + next.ActualWidth <= size.Width + 1 && point.Y + next.ActualHeight <= size.Height + 1,
                $"footer-visible-{size.Width}x{size.Height}-step-{step} [{point.X},{point.Y},{next.ActualWidth},{next.ActualHeight}; root {root.ActualWidth},{root.ActualHeight}]");
            var scroll = Find<ScrollViewer>("PageScroll"); Require(scroll.ActualHeight > 140, $"scrollable-content-room-{size.Width}x{size.Height}-step-{step}");
            layouts.Add(new { width = size.Width, height = size.Height, step, footer = new { point.X, point.Y, next.ActualWidth, next.ActualHeight }, contentHeight = scroll.ActualHeight });
            if (size.Width == 1060) ExportSvg(root, size, Path.Combine(directory, $"step-{step}.svg"));
        }
        File.WriteAllText(Path.Combine(directory, "checks.json"), JsonSerializer.Serialize(new { passed = true, events, layouts,
            pixelValidation = false, scope = "Real WPF routed navigation and arranged geometry. SVG is a layout reconstruction, not a captured native screenshot. Disconnected desktop has blank WPF compositor output; active-session visual and touch tests remain pending." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
    internal static List<string> CheckFreeNavigation(MainWindow window)
    {
        var events = new List<string>();
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); events.Add(name); }
        bool Red(string name) => ((SolidColorBrush)Find<TextBlock>(name).Foreground).Color == Color.FromRgb(255, 139, 139);
        Find<TextBox>("ImagePath").Clear();
        Click("SourceTab");
        Require(Find<StackPanel>("SourcePage").IsVisible && Red("NavTarget"), "empty-target-can-leave-and-is-red");
        Click("ReviewTab");
        Require(Find<StackPanel>("ReviewPage").IsVisible && Red("NavSource"), "empty-source-can-leave-and-review-renders");
        Click("ProgressTab");
        Require(Find<StackPanel>("ProgressPage").IsVisible && !Find<Button>("StopButton").IsEnabled && window.CompletedSession == null, "progress-preview-does-not-start-installation");
        Click("ResultTab");
        Require(Find<StackPanel>("ResultPage").IsVisible && Find<Border>("IncompleteCard").IsVisible && Find<TextBlock>("IncompleteItems").Text.Split('\n').Length == 4, "finish-lists-all-four-incomplete-steps");
        Require(Red("NavReview") && Red("NavProgress") && Red("NavResult"), "unfinished-review-progress-result-are-red");
        Find<RadioButton>("EnglishLanguage").IsChecked = true;
        Require(Find<TextBlock>("IncompleteHeading").Text == "Some items are incomplete" && Find<TextBlock>("IncompleteItems").Text.Contains("Location:"), "incomplete-summary-supports-english");
        Find<RadioButton>("ChineseLanguage").IsChecked = true;
        foreach (var pair in new[] { ("BootTab", "BootPage"), ("ContentTab", "ContentPage"), ("ReviewTab", "ReviewPage"), ("TargetTab", "TargetPage"), ("ProgressTab", "ProgressPage"), ("SourceTab", "SourcePage"), ("ResultTab", "ResultPage"), ("TargetTab", "TargetPage") })
        {
            Click(pair.Item1);
            Require(Find<StackPanel>(pair.Item2).IsVisible, "arbitrary-navigation-" + pair.Item1);
        }
        Require(window.CompletedSession == null && !Find<Grid>("SafetyOverlay").IsVisible, "tab-browsing-never-starts-install-or-opens-safety-dialog");
        Require(Red("NavSource") && Red("NavReview"), "finish-warning-remains-red-when-returning-to-configure");
        return events;
    }
    internal static void ExportSvg(FrameworkElement root, Size size, string path)
    {
        string N(double value) => value.ToString("0.###", CultureInfo.InvariantCulture);
        string Escape(string value) => SecurityElement.Escape(value) ?? "";
        string ColorOf(Brush? brush) => brush is SolidColorBrush solid && solid.Color.A > 0 ? $"#{solid.Color.R:X2}{solid.Color.G:X2}{solid.Color.B:X2}" : "none";
        var svg = new StringBuilder($"<svg xmlns='http://www.w3.org/2000/svg' width='{N(size.Width)}' height='{N(size.Height)}' viewBox='0 0 {N(size.Width)} {N(size.Height)}'><title>安装助手 · WPF 布局设计预览（不是屏幕截图）</title><rect width='100%' height='100%' fill='#F4F6FA'/>");
        var clip = 0;
        void Walk(DependencyObject item)
        {
            if (item is UIElement ui && ui.Visibility != Visibility.Visible) return;
            if (item is not Visual visual) return;
            var group = false;
            if (item is FrameworkElement element && element.ActualWidth > 0 && element.ActualHeight > 0)
            {
                var pos = visual.TransformToAncestor(root).Transform(new Point()); var x = N(pos.X); var y = N(pos.Y); var w = N(element.ActualWidth); var h = N(element.ActualHeight);
                if (element is ProgressBar progress)
                {
                    // Native track/indicator shapes are not Border children. Export
                    // their arranged size and actual value for the layout preview.
                    var ratio = Math.Clamp((progress.Value - progress.Minimum) / (progress.Maximum - progress.Minimum), 0, 1);
                    svg.Append($"<rect x='{x}' y='{y}' width='{w}' height='{h}' fill='{ColorOf(progress.Background)}'/>");
                    svg.Append($"<rect x='{x}' y='{y}' width='{N(element.ActualWidth * ratio)}' height='{h}' fill='{ColorOf(progress.Foreground)}'/>");
                    return;
                }
                if (element.ClipToBounds || element is ScrollContentPresenter or TextBox)
                { var id = "clip" + clip++; svg.Append($"<defs><clipPath id='{id}'><rect x='{x}' y='{y}' width='{w}' height='{h}'/></clipPath></defs><g clip-path='url(#{id})'>"); group = true; }
                if (element is Border border)
                    svg.Append($"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{N(border.CornerRadius.TopLeft)}' fill='{ColorOf(border.Background)}' stroke='{ColorOf(border.BorderBrush)}' stroke-width='{N(border.BorderThickness.Left)}'/>");
                else if (element is Panel panel && panel.Background != null)
                    svg.Append($"<rect x='{x}' y='{y}' width='{w}' height='{h}' fill='{ColorOf(panel.Background)}'/>");
                if (element is TextBlock text && text.Text.Length > 0)
                    Text(text.Text, pos, text.ActualWidth, text.FontSize, text.FontWeight, text.Foreground, text.TextWrapping != TextWrapping.NoWrap,
                        double.IsNaN(text.LineHeight) ? text.FontSize * 1.27 : text.LineHeight);
                else if (element is TextBox box && box.Text.Length > 0)
                    Text(box.Text, new Point(pos.X + 10, pos.Y + 8), box.ActualWidth - 20, box.FontSize, box.FontWeight, box.Foreground, false, box.FontSize * 1.27);
            }
            for (var i = 0; i < VisualTreeHelper.GetChildrenCount(item); i++) Walk(VisualTreeHelper.GetChild(item, i));
            if (group) svg.Append("</g>");
        }
        void Text(string value, Point pos, double width, double fontSize, FontWeight weight, Brush foreground, bool wrap, double lineHeight)
        {
            var lines = new List<string>(); var current = ""; double used = 0;
            foreach (var c in value)
            {
                var advance = c > 255 ? fontSize : c == ' ' ? fontSize * .35 : fontSize * .57;
                if (c == '\r') continue;
                if (c == '\n' || wrap && used + advance > width && current.Length > 0)
                { lines.Add(current); current = ""; used = 0; if (c == '\n') continue; }
                current += c; used += advance;
            }
            lines.Add(current);
            for (var i = 0; i < lines.Count; i++)
                svg.Append($"<text x='{N(pos.X)}' y='{N(pos.Y + fontSize + i * lineHeight)}' font-family='Microsoft YaHei UI,Microsoft YaHei,sans-serif' font-size='{N(fontSize)}' font-weight='{weight.ToOpenTypeWeight()}' fill='{ColorOf(foreground)}'>{Escape(lines[i])}</text>");
        }
        Walk(root); svg.Append("<text x='236' y='779' font-family='Microsoft YaHei,sans-serif' font-size='11' fill='#61728A'>设计预览 · 根据 WPF 布局重建，非原生窗口截图</text></svg>"); File.WriteAllText(path, svg.ToString());
    }
}




