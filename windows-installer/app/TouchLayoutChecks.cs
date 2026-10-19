using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace OxpInstaller;

// Exercises only routed UI events and synthetic disk snapshots. Never starts a write task.
internal static class TouchLayoutChecks
{
    internal static string Run(MainWindow window)
    {
        var directory = Path.Combine(Backend.Root, "logs", "touch-ui-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        Directory.CreateDirectory(directory);
        var events = new List<string>(); var layouts = new List<object>();
        events.AddRange(DiagnosticLogExportChecks.Run(directory));
        T Find<T>(string name) => (T)window.FindName(name);
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); events.Add(name); }
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(window.WindowState == WindowState.Maximized && window.WindowStyle == WindowStyle.SingleBorderWindow && window.ResizeMode == ResizeMode.CanResize, "default-maximized-with-system-chrome");
        Require(window.FindName("PhysicalMode") == null, "no-physical-mode-checkbox");
        ((PartitionPicker)window.FindName("PartitionSelector")).AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        BootSetupChecks.Acknowledge(window);
        Require(!Find<Expander>("LogExpander").IsExpanded, "logs-default-collapsed");
        var closingWindow = new MainWindow(rehearsal: true) { WindowState = WindowState.Normal, ShowActivated = false };
        ((PartitionPicker)closingWindow.FindName("PartitionSelector")).AutomaticReadEnabled = false;
        closingWindow.Show();
        var closingOperation = new CancellationTokenSource();
        typeof(MainWindow).GetField("operation", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(closingWindow, closingOperation);
        var closedAfterCleanup = false; closingWindow.Closed += (_, _) => closedAfterCleanup = true;
        closingWindow.Close();
        Require(!closedAfterCleanup && closingWindow.IsVisible && closingOperation.IsCancellationRequested, "close-requests-cancellation-and-waits-for-cleanup");
        closingWindow.FinishOperation();
        Require(closedAfterCleanup && !closingWindow.IsVisible, "cleanup-finished-window-closes-automatically");
        events.AddRange(WizardChecks.CheckFreeNavigation(window));
        var picker = Find<PartitionPicker>("PartitionSelector");
        Require(window.FindName("DebugMode") == null && window.FindName("AdvancedButton") == null,
            "debug-entry-removed");
        Require(picker.ExampleButton.Visibility == Visibility.Collapsed && Find<Expander>("DeveloperOptions").Visibility == Visibility.Collapsed
            && Find<CheckBox>("UsePrepared").IsChecked == false, "development-options-remain-hidden");
        picker.ExampleButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(picker.Disks.Items.Count == 0, "hidden-example-action-is-inactive");
        void Load(bool example)
        {
            picker.LoadSnapshot(PartitionInventory.ExampleJson, example);
            picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().First(r => r.Space != null);
            picker.CapacityInput.Text = "64";
        }
        Load(true); Click("NextButton");
        Require(Find<StackPanel>("TargetPage").IsVisible && Find<TextBlock>("ValidationMessage").Text.Length > 0, "example-cannot-enter-physical-installation");
        Load(false);
        bool TargetRed() => ((SolidColorBrush)Find<TextBlock>("NavTarget").Foreground).Color == Color.FromRgb(255,139,139);
        Require(!TargetRed(), "valid-64g-clears-target-error");
        Require(((SolidColorBrush)Find<TextBlock>("NavTarget").Foreground).Color == Color.FromRgb(134,239,172), "valid-target-is-green");
        picker.Capacity100Button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(picker.Selection.Capacity == 100 * PartitionInventory.GiB && !TargetRed(), "valid-100g-clears-target-error");
        Require(picker.AllSpaceButton.Visibility == Visibility.Collapsed && !picker.AllSpaceButton.IsVisible,
            "all-space-entry-hidden-from-touch-layout");
        picker.CapacityInput.Text = "32";
        Require(TargetRed(), "invalid-capacity-marks-target-error");
        picker.Capacity64Button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(!TargetRed(), "preset-repairs-invalid-capacity-state");
        Click("NextButton");
        Require(Find<Grid>("SafetyOverlay").IsVisible && !Find<Grid>("WizardShell").IsEnabled && Find<StackPanel>("TargetPage").IsVisible, "next-opens-blocking-backup-confirmation-before-navigation");
        var safetyText = Find<TextBlock>("SafetyMessage").Text;
        Require((safetyText.Contains("格式化") || safetyText.Contains("formats")) && Find<TextBlock>("SafetyTarget").Text.Contains("Disk"), "warning-identifies-formatting-and-target");
        Click("SafetyCancel");
        Require(!Find<Grid>("SafetyOverlay").IsVisible && Find<StackPanel>("TargetPage").IsVisible, "cancel-remains-on-target");
        Click("NextButton"); Click("SafetyContinue");
        Require(Find<StackPanel>("SourcePage").IsVisible && window.CompletedSession == null, "acknowledge-only-navigates-without-starting-installation");
        window.PreviewStep(3); Click("NextButton");
        Require(Find<StackPanel>("ReviewPage").IsVisible && Find<TextBlock>("ValidationMessage").Text.Length > 0 && window.CompletedSession == null, "final-install-requires-separate-consent");
        Require(Find<CheckBox>("PhysicalConsent").FontWeight == FontWeights.Bold
            && ((SolidColorBrush)Find<Border>("PhysicalConsentBorder").BorderBrush).Color.R >= 180,
            "unchecked-consent-has-bold-text-and-highlighted-border");
        Require(!SystemParameters.ClientAreaAnimation || ((SolidColorBrush)Find<Border>("PhysicalConsentBorder").BorderBrush).HasAnimatedProperties,
            "unchecked-consent-pulses-when-system-animations-enabled");
        Find<CheckBox>("PhysicalConsent").IsChecked = true; picker.CapacityInput.Text = "65";
        Require(((SolidColorBrush)Find<Border>("PhysicalConsentBorder").BorderBrush).Color == Color.FromRgb(196,138,50), "checking-consent-clears-highlight");
        Require(Find<CheckBox>("PhysicalConsent").IsChecked != true, "changed-capacity-invalidates-consent");
        Find<CheckBox>("PhysicalConsent").IsChecked = true; Click("NextButton");
        Require(window.CompletedSession == null && Find<TextBlock>("ValidationMessage").Text.Length > 0, "stale-acknowledgement-cannot-start-installation");
        picker.CapacityInput.Text = "64";
        var root = Find<Grid>("WindowRoot");
        foreach (var english in new[] { false, true })
        foreach (var size in new[] { new Size(640,360), new Size(800,450), new Size(853,480), new Size(960,540), new Size(1280,720), new Size(1280,800), new Size(1920,1080) })
        {
            Find<RadioButton>(english ? "EnglishLanguage" : "ChineseLanguage").IsChecked = true;
            window.Width = size.Width; window.Height = size.Height; window.UpdateLayout();
            void Inside(FrameworkElement element, string name)
            {
                var p = element.TransformToAncestor(root).Transform(new Point());
                Require(p.X >= -1 && p.Y >= -1 && p.X + element.ActualWidth <= root.ActualWidth + 1 && p.Y + element.ActualHeight <= root.ActualHeight + 1, name);
            }
            foreach (var step in Enumerable.Range(0,8))
            {
                window.PreviewStep(step); window.UpdateLayout();
                if (step == 5)
                    Require(Find<TextBlock>("ProgressDetail").Text.Contains("86.20%") && Find<TextBlock>("ProgressDetail").Text.Contains("04.42")
                        && !Find<ProgressBar>("Progress").IsIndeterminate, "overall-progress-two-decimals-and-step-code");
                var footer = Find<Button>(step == 5 ? "StopButton" : "NextButton");
                var suffix = $"{(english ? "en" : "zh")}-{size.Width}x{size.Height}-step{step}";
                Inside(footer,"footer-visible-" + suffix);
                Inside(Find<RadioButton>("ChineseLanguage"),"language-visible-" + suffix);
                Require(footer.ActualHeight >= 48, "footer-touch-height-" + suffix);
                var scroll = Find<ScrollViewer>("PageScroll");
                Require(scroll.ActualHeight >= 80 && scroll.PanningMode == PanningMode.VerticalOnly, "vertical-touch-content-room-" + suffix);
                Require(scroll.ExtentWidth <= scroll.ViewportWidth + 1, "no-horizontal-page-overflow-" + suffix);
                if (step == 5)
                {
                    var stop = Find<Button>("StopButton");
                    var stopPosition = stop.TransformToAncestor(root).Transform(new Point());
                    Require(stopPosition.Y < 60 && ((SolidColorBrush)stop.Background).Color == Color.FromRgb(180,35,24), "stop-is-red-at-top-right-" + suffix);
                    var logExpander = Find<Expander>("LogExpander");
                    Require(!logExpander.IsExpanded && !Find<TextBox>("LogText").IsVisible, "collapsed-log-does-not-take-page-space-" + suffix);
                    var title = Find<TextBlock>("ProgressTitle"); var bar = Find<ProgressBar>("Progress");
                    var titlePosition = title.TransformToAncestor(root).Transform(new Point());
                    var barPosition = bar.TransformToAncestor(root).Transform(new Point());
                    Require(barPosition.Y - titlePosition.Y - title.ActualHeight < 65, "progress-title-to-bar-gap-is-compact-" + suffix);
                    if (size.Width is 853 or 1280 && size.Height != 800) Capture(root,size,Path.Combine(directory,suffix));
                    logExpander.IsExpanded = true; window.UpdateLayout();
                    Require(Find<TextBox>("LogText").IsVisible && Find<TextBox>("LogText").ActualHeight >= 180, "expanded-log-has-readable-height-" + suffix);
                    var export = Find<Button>("ExportLogButton");
                    export.BringIntoView(); window.UpdateLayout();
                    Inside(export, "export-reachable-" + suffix);
                    Require(export.ActualHeight >= 48, "export-touch-height-" + suffix);
                    scroll.ScrollToTop(); window.UpdateLayout();
                    if (size.Height >= 720)
                    {
                        Inside(Find<TextBox>("LogText"), "log-fills-space-without-clipping-" + suffix);
                        Require(Find<TextBox>("LogText").ActualHeight > (size.Height >= 800 ? 240 : 180), "log-grows-with-window-" + suffix);
                    }
                    if (size.Width is 853 or 1280 && size.Height != 800) Capture(root,size,Path.Combine(directory,suffix+"-expanded"));
                    logExpander.IsExpanded = false; window.UpdateLayout();
                }
                if (step == 0 && size.Width == 1280 && size.Height == 720)
                {
                    picker.CapacityPanel.BringIntoView(); window.UpdateLayout();
                    Capture(root,size,Path.Combine(directory,suffix+"-capacity"));
                    scroll.ScrollToTop(); window.UpdateLayout();
                }
                if (step == 3 && size.Width == 1280 && size.Height == 720)
                    Capture(root,size,Path.Combine(directory,suffix+"-consent"));
                if (step == 2)
                {
                    var options = (InstallerOptionsPanel)Find<StackPanel>("ComponentOptionsHost").Children[0];
                    options.RepairsExpander.IsExpanded = true; window.UpdateLayout();
                    Require(scroll.ExtentWidth <= scroll.ViewportWidth + 1, "expanded-repairs-no-horizontal-overflow-" + suffix);
                    foreach (var option in options.OptionBoxes.Values)
                        Require(option.ActualHeight >= 48 && option.ActualWidth > 80, "option-touch-target-" + option.Tag + "-" + suffix);
                    if (size.Width == 1280 && size.Height == 720) Capture(root,size,Path.Combine(directory,suffix+"-expanded"));
                    options.RepairsExpander.IsExpanded = false; window.UpdateLayout();
                }
                if (step == 4)
                {
                    var boot = (BootOptionsPanel)Find<StackPanel>("BootOptionsHost").Children[0];
                    boot.InstallChoice.IsChecked = true; window.UpdateLayout();
                    Require(boot.Plus.ActualHeight >= 64 && boot.Minus.ActualWidth >= 64 && boot.Seconds.ActualHeight >= 64, "boot-stepper-touch-target-" + suffix);
                    Require(new[] { boot.SteamOsChoice, boot.WindowsChoice, boot.ForeverChoice, boot.TimedChoice }.All(choice => choice.ActualHeight >= 64), "boot-choice-touch-target-" + suffix);
                    Require(scroll.ExtentWidth <= scroll.ViewportWidth + 1, "boot-settings-no-horizontal-overflow-" + suffix);
                }
                if (step == 0)
                {
                    scroll.ScrollToBottom(); window.UpdateLayout();
                    Require(scroll.ScrollableHeight <= 0 || scroll.VerticalOffset > 0, "bottom-content-reachable-" + suffix);
                    scroll.ScrollToTop(); window.UpdateLayout();
                }
                layouts.Add(new { english, width=size.Width, height=size.Height, step, contentHeight=scroll.ActualHeight });
                if (size.Width is 853 or 1280 && size.Height != 800 && step is 0 or 1 or 2 or 4)
                    Capture(root,size,Path.Combine(directory,suffix));
            }
            window.PreviewStep(0); Click("NextButton"); window.UpdateLayout();
            Require(Find<Grid>("SafetyOverlay").IsVisible, "warning-visible-" + size + english);
            Inside(Find<Button>("SafetyCancel"),"warning-cancel-reachable-" + size + english);
            Inside(Find<Button>("SafetyContinue"),"warning-continue-reachable-" + size + english);
            if (size.Width == 853) Capture(root,size,Path.Combine(directory,english ? "warning-en" : "warning-zh"));
            Click("SafetyCancel");
        }
        File.WriteAllText(Path.Combine(directory,"checks.json"),JsonSerializer.Serialize(new { passed=true,events,layouts,
            scope="WPF layout and routed UI regression checks with synthetic disk snapshots; no installation or disk writes. Physical finger gestures and handheld DPI still need device validation." },new JsonSerializerOptions { WriteIndented=true }));
        return directory;
    }
    private static void Capture(FrameworkElement root, Size size, string path)
    {
        WizardChecks.ExportSvg(root,size,path+".svg");
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth),(int)Math.Ceiling(root.ActualHeight),96,96,PixelFormats.Pbgra32);
        bitmap.Render(root);
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var file = File.Create(path+".png"); encoder.Save(file);
    }
}
