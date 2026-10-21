using System.Buffers.Binary;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace OxpInstaller;

// Synthetic UI/store checks; startup may read firmware, never writes it or installs.
internal static class BootSetupChecks
{
    internal static string Run(MainWindow window)
    {
        RenderOptions.ProcessRenderMode = System.Windows.Interop.RenderMode.SoftwareOnly;
        var directory = Path.Combine(Backend.Root, "logs", "boot-setup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        Directory.CreateDirectory(directory);
        var events = new List<string>();
        void Require(bool value, string name) { if (!value) throw new IOException(name); events.Add(name); }
        void Refuse(Action action, string name) { try { action(); } catch (IOException) { events.Add(name); return; } throw new IOException("Accepted: " + name); }
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var picker = Find<PartitionPicker>("PartitionSelector");
        picker.AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        Require(Find<Grid>("BootPrerequisitesOverlay").IsVisible && !Find<Grid>("WizardShell").IsEnabled && !picker.BootPrerequisitesReady, "prerequisites-block-location-before-disk-inventory");
        Require(!Find<Button>("BootPrerequisitesContinue").IsEnabled, "prerequisites-require-explicit-acknowledgement");
        Click("BootPrerequisitesContinue");
        Require(Find<Grid>("BootPrerequisitesOverlay").IsVisible, "unacknowledged-routed-event-cannot-bypass-prerequisites");
        FirmwareBoot.RequireSecureBootDisabled([0]);
        foreach (var state in new byte[]?[] { null, [], [1], [2], [0, 0] })
            Refuse(() => FirmwareBoot.RequireSecureBootDisabled(state), "secure-boot-rejects-enabled-or-unverified-" + (state == null ? "missing" : Convert.ToHexString(state)));
        foreach (var failure in new[] { "Secure Boot is still enabled", "Firmware read failed" })
        {
            window.SecureBootPreflight = () => throw new IOException(failure);
            Click("BootPrerequisitesShow");
            Find<CheckBox>("BootPrerequisitesConsent").IsChecked = true;
            Click("BootPrerequisitesContinue");
            Require(Find<Grid>("BootPrerequisitesOverlay").IsVisible && !picker.BootPrerequisitesReady
                && !Find<Button>("NextButton").IsEnabled && Find<TextBlock>("BootPrerequisitesStatus").Text.Contains(failure),
                "enabled-or-unreadable-secure-boot-blocks-warning-dismissal-" + failure);
        }
        var probes = 0;
        window.SecureBootPreflight = () => { if (++probes > 1) throw new IOException("changed-before-dismissal"); };
        Click("BootPrerequisitesShow");
        Find<CheckBox>("BootPrerequisitesConsent").IsChecked = true;
        Click("BootPrerequisitesContinue");
        Require(probes == 2 && Find<Grid>("BootPrerequisitesOverlay").IsVisible && !picker.BootPrerequisitesReady,
            "warning-dismissal-rechecks-current-firmware-state");
        window.SecureBootPreflight = () => { };
        foreach (var english in new[] { false, true })
        {
            // Check entry into the warning from the location page in both languages.
            if (Find<Grid>("BootPrerequisitesOverlay").IsVisible) Acknowledge(window);
            Find<RadioButton>(english ? "EnglishLanguage" : "ChineseLanguage").IsChecked = true;
            window.SecureBootPreflight = () => FirmwareBoot.RequireSecureBootDisabled([1]);
            Click("BootPrerequisitesShow");
            Find<CheckBox>("BootPrerequisitesConsent").IsChecked = true;
            Click("BootPrerequisitesContinue");
            window.Width = 640; window.Height = 360; window.UpdateLayout();
            foreach (var name in new[] { "BootPrerequisitesExit", "BootPrerequisitesContinue", "BootPrerequisitesConsent" })
            {
                var element = Find<FrameworkElement>(name);
                var root = Find<Grid>("WindowRoot"); var at = element.TransformToAncestor(root).Transform(new Point());
                Require(at.X >= 0 && at.Y >= 0 && at.X + element.ActualWidth <= root.ActualWidth + 1
                    && at.Y + element.ActualHeight <= root.ActualHeight + 1, "blocked-prerequisites-controls-visible-" + english + "-" + name);
            }
            Require(Find<Grid>("BootPrerequisitesOverlay").IsVisible && !picker.BootPrerequisitesReady,
                "actual-enabled-state-message-blocks-entry-" + english);
            Capture(Find<Grid>("WindowRoot"), Path.Combine(directory, $"prerequisites-enabled-{(english ? "en" : "zh")}-640x360.png"));
            window.SecureBootPreflight = () => { };
            Click("BootPrerequisitesShow");
            Require(Find<TextBlock>("BootPrerequisitesMessage").Text.Contains("BitLocker") && Find<TextBlock>("BootPrerequisitesMessage").Text.Contains("Secure Boot"), "prerequisites-name-encryption-and-secure-boot-" + english);
            foreach (var size in new[] { new Size(640, 360), new Size(853, 480), new Size(1280, 720) })
            {
                window.Width = size.Width; window.Height = size.Height; window.UpdateLayout();
                var root = Find<Grid>("WindowRoot");
                foreach (var name in new[] { "BootPrerequisitesExit", "BootPrerequisitesContinue", "BootPrerequisitesConsent" })
                {
                    var element = Find<FrameworkElement>(name); var at = element.TransformToAncestor(root).Transform(new Point());
                    Require(at.X >= 0 && at.Y >= 0 && at.X + element.ActualWidth <= root.ActualWidth + 1 && at.Y + element.ActualHeight <= root.ActualHeight + 1,
                        $"prerequisites-controls-visible-{english}-{size}-{name}");
                }
                Capture(root, Path.Combine(directory, $"prerequisites-{(english ? "en" : "zh")}-{size.Width}x{size.Height}.png"));
            }
            Acknowledge(window);
            Require(!Find<Grid>("BootPrerequisitesOverlay").IsVisible && Find<Grid>("WizardShell").IsEnabled && picker.BootPrerequisitesReady && window.CompletedSession == null, "acknowledgement-opens-location-without-installation-" + english);
            window.PreviewStep(4);
            var panel = (BootOptionsPanel)Find<StackPanel>("BootOptionsHost").Children[0];
            window.UpdateLayout();
            var choiceAt = panel.MakeDefaultChoice.TransformToAncestor(Find<Grid>("WindowRoot")).Transform(new Point());
            Require(choiceAt.Y < 300 && panel.MakeDefaultChoice.ActualHeight >= 48, "firmware-choice-visible-near-top-with-touch-target-" + english);
            Require(panel.MakeDefaultChoice.IsEnabled && panel.MakeDefaultBoot, "internal-firmware-default-selected-" + english);
            if (!english)
            {
                Require(panel.InstallChoice.IsChecked == true && panel.Selection == new RefindChoice("SteamOS", 2), "refind-install-selected-by-default-with-two-second-timeout-" + english);
                panel.InstallChoice.IsChecked = false;
                Require(panel.Selection == null, "refind-install-can-be-opted-out-" + english);
            }
            else Require(panel.InstallChoice.IsChecked == false && panel.Selection == null, "refind-opt-out-survives-language-change-" + english);
            panel.InstallChoice.IsChecked = true;
            panel.MakeDefaultChoice.IsChecked = false;
            Require(!panel.MakeDefaultBoot, "uncheck-keeps-original-order-" + english);
            panel.MakeDefaultChoice.IsChecked = true;
            Find<RadioButton>("ExternalTarget").IsChecked = true;
            Require(!panel.MakeDefaultChoice.IsEnabled && !panel.MakeDefaultBoot, "external-mode-disables-host-default-" + english);
            Find<RadioButton>("InternalTarget").IsChecked = true;
            panel.InstallChoice.IsChecked = true;
            Require(panel.MakeDefaultBoot && panel.Selection != null, "refind-and-firmware-default-both-selected-" + english);
            var scanLine = panel.Configuration().Split('\n').Single(line => line.Contains("OXP3-rEFInd/drivers_x64"));
            var directive = scanLine.Split(' ', StringSplitOptions.RemoveEmptyEntries)[0];
            var refindTokens = Regex.Matches(Encoding.Unicode.GetString(File.ReadAllBytes(Path.Combine(Backend.Root, "components/refind/refind_x64.efi"))), "[a-z_]{5,}")
                .Select(match => match.Value).ToHashSet(StringComparer.Ordinal);
            Require(refindTokens.Contains(directive), "driver-scan-directive-recognized-by-bundled-refind-" + english);
            Require(!panel.Configuration().Contains("\ndriver_dirs "), "unrecognized-driver-directive-not-exported-" + english);
            Capture(Find<Grid>("WindowRoot"), Path.Combine(directory, $"boot-options-{(english ? "en" : "zh")}.png"));
            panel.InstallChoice.IsChecked = false; window.PreviewStep(0);
        }
        Find<RadioButton>("ChineseLanguage").IsChecked = true;
        Refuse(() => InstallationController.ValidateRequest(new(InstallationTargetKind.ExternalDisk, "absent.img", false, Physical: true, MakeDefaultBoot: true)), "external-request-cannot-change-firmware");
        Refuse(() => InstallationController.ValidateRequest(new(InstallationTargetKind.InternalShared, "absent.img", false, MakeDefaultBoot: true)), "rehearsal-request-cannot-change-firmware");
        var oldRequest = JsonSerializer.Deserialize<InstallationRequest>("{\"Kind\":0,\"Source\":\"absent.img\",\"Prepared\":false}")!;
        Require(!oldRequest.MakeDefaultBoot, "legacy-request-keeps-firmware-default");
        var request = oldRequest with { Physical = true, MakeDefaultBoot = true };
        Require(JsonSerializer.Deserialize<InstallationRequest>(JsonSerializer.Serialize(request))!.MakeDefaultBoot, "default-choice-survives-request-serialization");
        CheckFirmware(directory, Require, Refuse);
        File.WriteAllText(Path.Combine(directory, "checks.json"), JsonSerializer.Serialize(new { passed = true, events, scope = "Synthetic WPF events and in-memory firmware only; no disk writes, restart, BitLocker or NVRAM changes." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
    internal static void Acknowledge(MainWindow window)
    {
        var native = window.SecureBootPreflight;
        window.SecureBootPreflight = () => { };
        try
        {
            ((CheckBox)window.FindName("BootPrerequisitesConsent")).IsChecked = true;
            ((Button)window.FindName("BootPrerequisitesContinue")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        }
        finally { window.SecureBootPreflight = native; }
    }
    private static void CheckFirmware(string directory, Action<bool, string> require, Action<Action, string> refuse)
    {
        var esp = new PreparedPartition(17, "esp", new Guid("c12a7328-f81f-11d2-ba4b-00a0c93ec93b"), Guid.NewGuid(), 1048576, 64 * 1048576, 0);
        // Existing Windows boot entry plus another entry; 6000 is occupied but not ordered.
        byte[] original = [1, 0, 7, 0];
        foreach (var mode in new[] { "append", "default", "reject-order", "write-then-fail", "concurrent-order", "malformed" })
        {
            var run = Path.Combine(directory, mode); Directory.CreateDirectory(run);
            var store = new Dictionary<string, (byte[] Data, uint Attributes)> { ["BootOrder"] = (mode == "malformed" ? [1] : original.ToArray(), 7), ["Boot0001"] = ([42], 7), ["Boot6000"] = ([99], 7) };
            (byte[] Data, uint Attributes)? Read(string name) => store.TryGetValue(name, out var value) ? (value.Data.ToArray(), value.Attributes) : null;
            var firstOrderWrite = true;
            void Write(string name, byte[] data, uint attributes)
            {
                require(File.Exists(Path.Combine(run, "firmware-before.json")), mode + "-backup-precedes-write");
                if (name == "BootOrder" && firstOrderWrite)
                {
                    firstOrderWrite = false;
                    if (mode == "reject-order") throw new IOException("Injected firmware rejection.");
                    store[name] = (data.ToArray(), attributes);
                    if (mode == "write-then-fail") throw new IOException("Injected failure after write.");
                }
                else if (data.Length == 0) store.Remove(name);
                else store[name] = (data.ToArray(), attributes);
                if (mode == "concurrent-order" && name == "Boot6001") store["BootOrder"] = ([9, 0], 7);
            }
            void Register() => FirmwareBoot.RegisterCore(esp, run, mode != "append", Read, Write);
            if (mode is "append" or "default")
            {
                Register(); var after = store["BootOrder"].Data;
                require(BinaryPrimitives.ReadUInt16LittleEndian(after.AsSpan(mode == "default" ? 0 : original.Length)) == 0x6001, mode + "-uses-unused-entry");
                require(after.AsSpan(mode == "default" ? 2 : 0, original.Length).SequenceEqual(original), mode + "-preserves-relative-original-order");
                using var backup = JsonDocument.Parse(File.ReadAllText(Path.Combine(run, "firmware-before.json")));
                require(Convert.FromBase64String(backup.RootElement.GetProperty("originalBootOrder").GetString()!).SequenceEqual(original), mode + "-backup-has-original-order");
                using var result = JsonDocument.Parse(File.ReadAllText(Path.Combine(run, "firmware-result.json")));
                require(result.RootElement.GetProperty("defaultPreserved").GetBoolean() == (mode == "append"), mode + "-result-reports-actual-choice");
            }
            else
            {
                refuse(Register, mode + "-fails-registration");
                require(!File.Exists(Path.Combine(run, "firmware-result.json")), mode + "-never-reports-success");
                if (mode is "reject-order" or "write-then-fail") require(store["BootOrder"].Data.SequenceEqual(original) && !store.ContainsKey("Boot6001"), mode + "-restores-order-and-removes-owned-entry");
                if (mode == "concurrent-order") require(store["BootOrder"].Data.SequenceEqual(new byte[] { 9, 0 }), "concurrent-firmware-change-is-not-overwritten");
                if (mode == "malformed") require(!File.Exists(Path.Combine(run, "firmware-before.json")), "malformed-order-fails-before-backup-or-write");
            }
            require(store["Boot0001"].Data.SequenceEqual(new byte[] {42}) && store["Boot6000"].Data.SequenceEqual(new byte[] {99}), mode + "-existing-boot-entries-preserved");
        }
    }
    private static void Capture(FrameworkElement root, string path)
    {
        root.Dispatcher.Invoke(() => { }, System.Windows.Threading.DispatcherPriority.ApplicationIdle);
        root.UpdateLayout();
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth), (int)Math.Ceiling(root.ActualHeight), 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(root); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var file = File.Create(path); encoder.Save(file);
    }
}
