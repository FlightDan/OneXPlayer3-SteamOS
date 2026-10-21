using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace OxpInstaller;

internal static class OfficialSystemProgressChecks
{
    internal static async Task<string> RunImportUiAsync(MainWindow window, string bundle)
    {
        var originalWorkspace = InstallerWorkspace.DirectoryPath;
        var workspaceField = typeof(InstallerWorkspace).GetField("<DirectoryPath>k__BackingField", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!;
        var directory = Path.Combine(originalWorkspace, "local-import-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Require(bool value, string label) { if (!value) throw new IOException(label); checks.Add(label); }
        var panel = ((StackPanel)window.FindName("OfficialDownloadHost")).Children.OfType<OfficialDownloadPanel>().Single();
        T Field<T>(string name) => (T)typeof(OfficialDownloadPanel).GetField(name, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.GetValue(panel)!;
        try
        {
            workspaceField.SetValue(null, directory);
            window.PreviewStep(1); window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
            ((Button)window.FindName("OfficialSourceTab")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Field<CheckBox>("agreement").IsChecked = false;
            await panel.DownloadAsync();
            Require(!OfficialSystem.HasPreparedSource() && Field<TextBlock>("status").Text.Contains("条款"), "online-download-still-requires-consent");
            var busyEvents = new List<bool>(); panel.BusyChanged += busyEvents.Add;
            await panel.DownloadAsync(bundle);
            Require(OfficialSystem.IsBundleReady() && !OfficialSystem.IsCached(), "local-raucb-imports-without-download-consent-or-root-reconstruction");
            var staged = OfficialSystem.RequirePreparedSource();
            Require(Field<TextBox>("localPath").Text == staged, "import-displays-workspace-bundle-path");
            Require(busyEvents.SequenceEqual(new[] { true, false }) && !panel.IsBusy && Field<Button>("browse").IsEnabled, "import-restores-controls-and-reports-busy-state");
            await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
            Require(Field<TextBlock>("localStatus").IsVisible && Field<TextBlock>("localStatus").Text.Contains("下一步"), "success-feedback-visible-beside-local-file");
            var invalid = Path.Combine(directory, "invalid.raucb"); await File.WriteAllTextAsync(invalid, "invalid bundle");
            await panel.DownloadAsync(invalid);
            await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
            Require(Field<TextBlock>("localStatus").IsVisible && Field<TextBlock>("localStatus").Text.Contains("准备未完成"), "invalid-local-bundle-shows-nearby-error");
            Require(OfficialSystem.IsBundleReady() && Field<TextBox>("localPath").Text == staged && !panel.IsBusy, "failed-import-preserves-previous-ready-bundle");
            await panel.DownloadAsync(bundle);
            window.Width = 1060; window.Height = 720; window.UpdateLayout();
            Field<TextBlock>("localStatus").BringIntoView();
            await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
            var root = (FrameworkElement)window.Content;
            var bitmap = new RenderTargetBitmap((int)root.ActualWidth, (int)root.ActualHeight, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(root); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var image = File.Create(Path.Combine(directory, "local-import.png"))) encoder.Save(image);
            var recovery = Path.Combine(originalWorkspace, "source", "steamdeck-oobe-repair-20260707.10-3.8.14.img");
            ((TextBox)window.FindName("ImagePath")).Text = recovery;
            ((Button)window.FindName("NextButton")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Require(((StackPanel)window.FindName("ContentPage")).IsVisible, "imported-bundle-allows-next-page");
            return JsonSerializer.Serialize(new { passed = true, checks, directory }, new JsonSerializerOptions { WriteIndented = true });
        }
        finally { workspaceField.SetValue(null, originalWorkspace); }
    }

    internal static async Task<string> RunLocalBundleAsync(MainWindow window, string bundle)
    {
        var originalWorkspace = InstallerWorkspace.DirectoryPath;
        var workspaceField = typeof(InstallerWorkspace).GetField("<DirectoryPath>k__BackingField", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!;
        var directory = Path.Combine(originalWorkspace, "local-bundle-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Require(bool value, string label) { if (!value) throw new IOException(label); checks.Add(label); }
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var panel = Find<StackPanel>("OfficialDownloadHost").Children.OfType<OfficialDownloadPanel>().Single();
        T PanelField<T>(string name) => (T)typeof(OfficialDownloadPanel).GetField(name, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.GetValue(panel)!;
        var recovery = Path.Combine(originalWorkspace, "source", "steamdeck-oobe-repair-20260707.10-3.8.14.img");
        try
        {
            workspaceField.SetValue(null, directory);
            window.PreviewStep(1); window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show(); Click("OfficialSourceTab");
            Find<TextBox>("ImagePath").Text = recovery;
            PanelField<CheckBox>("agreement").IsChecked = true;
            await panel.DownloadAsync();
            Require(OfficialSystem.IsBundleReady() && !OfficialSystem.IsCached(), "online-raucb-ready-without-rebuilding-root");
            Require(PanelField<TextBox>("localPath").Text.EndsWith(".raucb"), "online-download-fills-local-bundle-path");
            await panel.DownloadAsync(bundle);
            var staged = OfficialSystem.RequirePreparedSource();
            Require(staged.EndsWith(".raucb") && PanelField<TextBox>("localPath").Text == staged, "selected-local-raucb-fills-staged-path");
            Require(!File.Exists(Path.Combine(directory, "steamos-3.10/rootfs.img")), "local-selection-does-not-rebuild-root");
            Click("NextButton");
            Require(Find<StackPanel>("ContentPage").IsVisible, "raucb-source-advances-to-installation-contents");
            // Seed only the installation-preparation phase with existing real system data.
            // The earlier download/selection assertions run in a completely empty workspace.
            File.Copy(Path.Combine(originalWorkspace, "steamos-3.10/rootfs.img"), Path.Combine(directory, "steamos-3.10/rootfs.img"));
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(5));
            using var log = new StreamWriter(Path.Combine(directory, "preparation.log")) { AutoFlush = true };
            var prepared = await OfficialSystem.PrepareAsync(recovery, directory, line => { lock (log) log.WriteLine(line); }, timeout.Token);
            Require(OfficialSystem.IsCached() && File.Exists(prepared), "installation-preparation-rebuilds-root-and-integrates-recovery");
            return JsonSerializer.Serialize(new { passed = true, checks, directory,
                scope = "Real official RAUC bundle download, local selection handler, next-page navigation and VM source preparation. Reconstruction reuses an existing real root image seed. No physical installation." }, new JsonSerializerOptions { WriteIndented = true });
        }
        finally { workspaceField.SetValue(null, originalWorkspace); }
    }
    internal static async Task<string> RunUiAsync(MainWindow window)
    {
        var directory = Path.Combine(Backend.Root, "logs", "official-download-ui-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Require(bool value, string label) { if (!value) throw new IOException(label); checks.Add(label); }
        T Find<T>(string name) => (T)window.FindName(name);
        var source = Find<StackPanel>("SourcePage"); var host = Find<StackPanel>("OfficialDownloadHost");
        var panel = host.Children.OfType<OfficialDownloadPanel>().Single();
        bool WithinSource(DependencyObject item)
        {
            for (DependencyObject? current = item; current != null; current = LogicalTreeHelper.GetParent(current))
                if (current == source) return true;
            return false;
        }
        Require(WithinSource(Find<CheckBox>("Upgrade310")) && WithinSource(panel), "version-selection-and-download-on-system-page");
        Find<PartitionPicker>("PartitionSelector").AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        BootSetupChecks.Acknowledge(window);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Click("SourceTab");
        Require(Find<StackPanel>("SourceSubitems").IsVisible && Find<StackPanel>("RecoverySourceSection").IsVisible
            && !Find<StackPanel>("OfficialSourceSection").IsVisible, "prepare-system-opens-recovery-subpage");
        var recoveryPath = Find<TextBox>("ImagePath").Text;
        Click("OfficialSourceTab");
        Require(Find<StackPanel>("OfficialSourceSection").IsVisible && !Find<StackPanel>("RecoverySourceSection").IsVisible,
            "official-subitem-opens-independent-page");
        Click("BackButton");
        Require(Find<StackPanel>("RecoverySourceSection").IsVisible && Find<TextBox>("ImagePath").Text == recoveryPath,
            "back-to-recovery-preserves-selected-file");
        var stub = Path.Combine(directory, "navigation-only.img"); await File.WriteAllBytesAsync(stub, RecoveryImageChecks.Fixture());
        Find<TextBox>("ImagePath").Text = stub;
        Click("NextButton");
        Require(Find<StackPanel>("OfficialSourceSection").IsVisible && !Find<StackPanel>("ContentPage").IsVisible,
            "next-from-recovery-goes-to-310-before-contents");
        Click("NextButton");
        Require(OfficialSystem.HasPreparedSource() ? Find<StackPanel>("ContentPage").IsVisible
            : Find<StackPanel>("OfficialSourceSection").IsVisible && Find<TextBlock>("ValidationMessage").Text.Length > 0,
            "next-from-310-requires-prepared-system");
        Find<TextBox>("ImagePath").Text = recoveryPath;
        Click("ContentTab");
        Require(!Find<StackPanel>("SourceSubitems").IsVisible, "source-subitems-collapse-outside-prepare-system");
        foreach (var language in new[] { "ChineseLanguage", "EnglishLanguage" })
        foreach (var size in new[] { new Size(1060, 720), new Size(853, 480) })
        {
            Find<RadioButton>(language).IsChecked = true;
            window.Width = size.Width; window.Height = size.Height; window.PreviewStep(1);
            Click("OfficialSourceTab");
            await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
            window.UpdateLayout(); Find<ScrollViewer>("PageScroll").ScrollToTop(); window.UpdateLayout();
            Require(panel.ActualWidth > 300 && panel.ActualHeight > 80, "official-download-layout-" + language + size);
            var root = (FrameworkElement)window.Content;
            var point = host.TransformToAncestor(root).Transform(new Point());
            var scroll = Find<ScrollViewer>("PageScroll");
            var bounds = scroll.TransformToAncestor(root).Transform(new Point());
            Require(scroll.ScrollableHeight > 0 || host.ActualHeight <= scroll.ActualHeight + 1,
                "official-download-controls-reachable-" + language + size);
            var bitmap = new RenderTargetBitmap((int)root.ActualWidth, (int)root.ActualHeight, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(root); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using var image = File.Create(Path.Combine(directory, $"{language}-{size.Width}x{size.Height}.png")); encoder.Save(image);
            Click("RecoverySourceTab"); scroll.ScrollToTop(); window.UpdateLayout();
            var recoveryBitmap = new RenderTargetBitmap((int)root.ActualWidth, (int)root.ActualHeight, 96, 96, PixelFormats.Pbgra32);
            recoveryBitmap.Render(root); var recoveryEncoder = new PngBitmapEncoder(); recoveryEncoder.Frames.Add(BitmapFrame.Create(recoveryBitmap));
            using var recoveryImage = File.Create(Path.Combine(directory, $"recovery-{language}-{size.Width}x{size.Height}.png")); recoveryEncoder.Save(recoveryImage);
        }
        using var operation = new CancellationTokenSource();
        var field = typeof(OfficialDownloadPanel).GetField("operation", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        var refresh = typeof(MainWindow).GetMethod("UpdateNavigationState", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        field.SetValue(panel, operation); refresh.Invoke(window, null);
        Require(!Find<Button>("NextButton").IsEnabled && !Find<Button>("BrowseWorkspaceButton").IsEnabled
            && !Find<CheckBox>("Upgrade310").IsEnabled && !Find<StackPanel>("DownloadHost").Children[0].IsEnabled,
            "predownload-locks-workspace-version-and-conflicting-download");
        panel.Pause(); Require(operation.IsCancellationRequested, "pause-cancels-official-preparation");
        field.SetValue(panel, null); refresh.Invoke(window, null);
        Require(Find<Button>("NextButton").IsEnabled
            && Find<Button>("BrowseWorkspaceButton").IsEnabled == !Find<PartitionPicker>("PartitionSelector").IsBusy,
            "controls-restored-after-preparation");
        return JsonSerializer.Serialize(new { passed = true, checks, directory }, new JsonSerializerOptions { WriteIndented = true });
    }
    internal static async Task<string> RunAsync()
    {
        var checks = new List<string>();
        void Require(bool value, string label) { if (!value) throw new IOException(label); checks.Add(label); }
        var payload = new byte[1024 * 1024]; RandomNumberGenerator.Fill(payload);
        foreach (long? length in new long?[] { payload.Length, null })
        {
            using var source = new MemoryStream(payload); using var destination = new MemoryStream();
            var events = new List<long>();
            await OfficialSystem.CopyDownloadAsync(source, destination, length, (bytes, total, speed) =>
            {
                Require(total == length && speed >= 0, "valid-download-size-and-speed"); events.Add(bytes);
            }, CancellationToken.None);
            Require(destination.ToArray().SequenceEqual(payload) && events[0] == 0 && events[^1] == payload.Length,
                length.HasValue ? "known-size-download-completes-with-actual-bytes" : "unknown-size-download-reports-bytes-without-inventing-total");
        }
        using (var truncated = new MemoryStream(payload))
        using (var target = new MemoryStream())
        {
            var rejected = false;
            try { await OfficialSystem.CopyDownloadAsync(truncated, target, payload.Length + 1, (_, _, _) => { }, CancellationToken.None); }
            catch (IOException) { rejected = true; }
            Require(rejected, "truncated-download-cannot-complete");
        }
        using (var source = new MemoryStream(payload))
        using (var target = new MemoryStream())
        {
            var cancelled = false;
            try { await OfficialSystem.CopyDownloadAsync(source, target, payload.Length, (_, _, _) => { }, new CancellationToken(true)); }
            catch (OperationCanceledException) { cancelled = true; }
            Require(cancelled && target.Length == 0, "cancel-before-read-prevents-download-write");
        }
        Require(OfficialSystem.AssemblyFraction("Attempt 1: Assembling   37.25% 10s") == .3725, "desync-real-format-parses");
        Require(OfficialSystem.AssemblyFraction("Attempt 2: Validating 50.00%") == null
            && OfficialSystem.AssemblyFraction("Attempt 2: Assembling 101.00%") == null, "validation-and-invalid-percent-do-not-credit-download");
        var tracker = new InstallationProgressTracker();
        foreach (var fraction in new[] { 0d, .1, .7, .2, .8, .9, 1 })
        {
            var previous = tracker.Percent;
            var next = tracker.Advance("preparing", (2 + 10 * fraction) / 32);
            Require(next >= previous && next <= 12, "official-substeps-and-retries-remain-monotonic");
        }
        var directory = Path.Combine(InstallationController.Work, "official-progress-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory); Directory.CreateDirectory(Path.Combine(directory, "store"));
        var input = Path.Combine(directory, "source.bin"); var index = Path.Combine(directory, "source.caibx");
        var output = Path.Combine(directory, "rebuilt.bin"); var executable = Path.Combine(Backend.Root, "runtime/desync/desync.exe");
        await File.WriteAllBytesAsync(input, payload);
        var cachedBefore = OfficialSystem.IsCached();
        var rejectedImport = false;
        try { await OfficialSystem.ImportRootAsync(input, CancellationToken.None); }
        catch (IOException) { rejectedImport = true; }
        Require(rejectedImport && OfficialSystem.IsCached() == cachedBefore, "invalid-local-image-rejected-without-changing-cache");
        await Backend.ProcessAsync(executable, ["make", "-s", Path.Combine(directory, "store"), index, input], _ => { }, CancellationToken.None);
        var observed = new List<double>();
        var transcript = await Backend.ProcessAsync(executable, ["extract", "-s", Path.Combine(directory, "store"), index, output], line =>
        {
            if (OfficialSystem.AssemblyFraction(line) is double value) observed.Add(value);
        }, CancellationToken.None, new Dictionary<string, string> { ["DESYNC_ENABLE_PARSABLE_PROGRESS"] = "1" });
        Require(observed.Count > 0 && observed[^1] == 1 && (await File.ReadAllBytesAsync(output)).SequenceEqual(payload),
            "bundled-desync-redirected-output-delivers-real-completion");
        await File.WriteAllTextAsync(Path.Combine(directory, "desync-progress.txt"), transcript);
        return JsonSerializer.Serialize(new { passed = true, checks, directory }, new JsonSerializerOptions { WriteIndented = true });
    }
}
