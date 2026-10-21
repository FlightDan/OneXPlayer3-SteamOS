using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

public static class OptionsChecks
{
    public static string Run(MainWindow window)
    {
        var events = new List<string>();
        var desktopLanguageDefaults = CheckDesktopLanguageDefaults(events);
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); events.Add(name); }
        // This UI check uses synthetic layouts, so suppress the automatic hardware inventory.
        typeof(PartitionPicker).GetField("automaticReadAttempted", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
            .SetValue((PartitionPicker)window.FindName("PartitionSelector"), true);
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        BootSetupChecks.Acknowledge(window);
        Color ContentColor() => ((SolidColorBrush)((TextBlock)window.FindName("NavContent")).Foreground).Color;
        Require(ContentColor() == Color.FromRgb(148, 169, 195), "unvisited-content-starts-neutral");
        ((Button)window.FindName("ContentTab")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(ContentColor() == Color.FromRgb(134, 239, 172), "valid-content-turns-green-after-entry");
        ((Button)window.FindName("TargetTab")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(ContentColor() == Color.FromRgb(134, 239, 172), "visited-content-keeps-completed-state");
        var panel = (InstallerOptionsPanel)((StackPanel)window.FindName("ComponentOptionsHost")).Children[0];
        var catalog = InstallerOptions.Catalog;
        Require(window.FindName("PhysicalMode") == null,"physical-mode-checkbox-removed");
        Require(((CheckBox)window.FindName("Upgrade310")).IsChecked==true,"official-3.10-source-selected-by-default");
        var modeBanner = ((TextBlock)window.FindName("ModeBanner")).Text;
        Require((modeBanner.Contains("备份") || modeBanner.Contains("Back up")) && !modeBanner.Contains("Beta"),"backup-and-formatting-are-explicit-in-release-banner");
        Require(panel.Selection.Repairs.Order().SequenceEqual(InstallerOptions.Defaults.Repairs.Order()), "repair-defaults-match-language");
        Require(!panel.RepairsExpander.IsExpanded, "device-repairs-start-collapsed");
        Require(!panel.Children.OfType<TextBlock>().Any(x => x.Text.Contains("系统更新") || x.Text.Contains("system updates"))
            && !panel.Describe().Contains("系统更新") && !panel.Describe().Contains("system updates"), "options-and-plan-do-not-promise-system-update-pause");
        Require(catalog.Repairs.Where(x => x.Available && x.Id is not ("refind" or "flathub-ustc")).All(x => panel.Selection.Repairs.Contains(x.Id)), "all-available-device-repairs-selected");
        Require(panel.Selection.Plugins.Order().SequenceEqual(catalog.Plugins.Where(x => x.Default).Select(x => x.Id).Order()), "plugin-defaults-match-catalog");
        Require(catalog.Repairs.All(x => x.Id != "waydroid") && catalog.Plugins.Any(x => x.Id == "waydroid"), "third-party-waydroid-is-in-third-party-category");
        Require(catalog.Repairs.Single(x => x.Id == "gamescope-env").Default, "new-game-mode-black-screen-fix-default-enabled");
        var boot = (BootOptionsPanel)((StackPanel)window.FindName("BootOptionsHost")).Children[0];
        Require(boot.InstallChoice.IsEnabled && boot.InstallChoice.IsChecked == true
            && boot.Selection == new RefindChoice("SteamOS", 2), "refind-install-selected-by-default-with-two-second-timeout");
        boot.InstallChoice.IsChecked = false;
        Require(boot.Selection == null, "refind-install-can-be-opted-out");
        boot.InstallChoice.IsChecked = true;
        Require(boot.Selection == new RefindChoice("SteamOS", 2), "refind-install-settings-reach-request");
        try { RefindInstallation.Validate(new("Windows", 5),null); throw new InvalidOperationException("Unbound Windows default accepted"); }
        catch (IOException) { events.Add("unidentified-windows-default-refused"); }
        var windowsSnapshot = "[{\"partitions\":[{\"isSystem\":true,\"gptType\":\"c12a7328-f81f-11d2-ba4b-00a0c93ec93b\",\"guid\":\"12345678-1234-1234-1234-123456789abc\"}]}]";
        var identified = new PartitionSelection(windowsSnapshot,false,0,0,0);
        Require(RefindInstallation.WindowsEsp(identified)=="12345678-1234-1234-1234-123456789abc","windows-esp-bound-to-gpt-identity");
        RefindInstallation.Validate(new("Windows",0),identified);
        Require(boot.Configuration().Contains("default_selection \"SteamOS\"") && boot.Configuration().Contains("timeout 2"), "refind-default-settings");
        boot.InstallChoice.IsChecked = true;
        boot.WindowsChoice.IsChecked = true;
        boot.Plus.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(boot.Configuration().Contains("default_selection \"Windows\"") && boot.Configuration().Contains("timeout 3"), "refind-windows-and-touch-plus");
        boot.Minus.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(boot.Seconds.Text == "2", "refind-touch-minus");
        boot.Seconds.Text = "1"; boot.Minus.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(boot.Seconds.Text == "1", "refind-timeout-lower-bound");
        boot.Seconds.Text = "3600"; boot.Plus.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(boot.Seconds.Text == "3600", "refind-timeout-upper-bound");
        boot.Seconds.Text = "bad";
        try { boot.Configuration(); throw new IOException("invalid-refind-timeout-accepted"); }
        catch (InvalidOperationException) { events.Add("invalid-refind-timeout-rejected"); }
        boot.Plus.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(boot.Seconds.Text == "3", "refind-invalid-timeout-adjustment-starts-from-two");
        boot.ForeverChoice.IsChecked = true;
        Require(boot.Configuration().Contains("timeout 0") && !boot.Seconds.IsEnabled && !boot.Plus.IsEnabled, "refind-wait-forever-disables-timer");
        var exported = Path.Combine(Backend.Root, "logs", "refind-settings-ui-check.conf");
        boot.WriteConfiguration(exported);
        Require(File.ReadAllText(exported) == boot.Configuration(), "refind-export-matches-settings");
        boot.Seconds.Text = "2"; boot.TimedChoice.IsChecked = true;
        var boxes = panel.OptionBoxes;
        Require(new[] { "steamgriddb", "protondb", "tabmaster", "css-loader", "autoflatpaks", "deck-settings", "hltb", "animation-changer" }
            .All(id => !boxes.ContainsKey(id)), "user-installed-third-party-plugins-are-not-bundled-options");
        ((RadioButton)window.FindName("ChineseLanguage")).IsChecked = true;
        Require(boxes["flathub-ustc"].IsChecked == true, "chinese-mirror-default-enabled");
        ((RadioButton)window.FindName("EnglishLanguage")).IsChecked = true;
        Require(boxes["flathub-ustc"].IsChecked == false, "english-mirror-default-disabled");
        boxes["flathub-ustc"].IsChecked = true;
        ((RadioButton)window.FindName("ChineseLanguage")).IsChecked = true;
        ((RadioButton)window.FindName("EnglishLanguage")).IsChecked = true;
        Require(boxes["flathub-ustc"].IsChecked == true, "explicit-mirror-choice-survives-language-change");
        boxes["flathub-ustc"].IsChecked = false;
        ((RadioButton)window.FindName("ChineseLanguage")).IsChecked = true;
        Require(boxes["flathub-ustc"].IsChecked == false, "explicit-mirror-opt-out-survives-chinese");
        boxes["hdr"].IsChecked = false; Require(!panel.Selection.Repairs.Contains("hdr"), "disabled-repair-is-absent-from-request");
        boxes["windows-reboot"].IsChecked = false; Require(!panel.Selection.Plugins.Contains("windows-reboot"), "disabled-project-plugin-is-absent-from-request");
        boxes["decky"].IsChecked = false;
        try { InstallerOptions.Validate(panel.Selection); throw new IOException("disabled-dependency-was-accepted"); } catch (IOException e) when (e.Message != "disabled-dependency-was-accepted") { events.Add("disabled-dependency-refused"); }
        boxes["decky"].IsChecked = true;
        ((RadioButton)window.FindName("EnglishLanguage")).IsChecked = true;
        Require(InstallerI18n.Language == "en-US" && ((Button)window.FindName("NextButton")).Content.ToString() == "Next", "english-navigation-applied");
        Require(((TextBlock)window.FindName("ModeBanner")).Text.Contains("Back up"),"backup-warning-translated");
        Require(((TextBlock)boxes["hdr"].Content).Text.Contains("Game mode HDR"), "english-repair-label-applied");
        Require(boxes["hdr"].IsChecked == false && boxes["windows-reboot"].IsChecked == false, "language-switch-preserves-disabled-choices");
        Require(boot.WindowsChoice.IsChecked == true && boot.Seconds.Text == "2" && boot.InstallChoice.IsChecked == true, "language-switch-preserves-refind-settings");
        var kde = panel.KdeChoice; kde.SelectedIndex = 1;
        Require(panel.Selection.KdeLanguage == "zh_CN" && panel.Selection.InstallerLanguage == "en-US", "kde-language-independent-of-installer-language");
        var json = JsonSerializer.Serialize(panel.Selection); var roundtrip = JsonSerializer.Deserialize<SelectedOptions>(json)!;
        InstallerOptions.Validate(roundtrip); Require(roundtrip.KdeLanguage == "zh_CN" && !roundtrip.Repairs.Contains("hdr"), "selection-roundtrip-retains-language-and-opt-outs");
        ((RadioButton)window.FindName("ChineseLanguage")).IsChecked = true; Require(((Button)window.FindName("NextButton")).Content.ToString() == "下一步", "chinese-navigation-restored");
        foreach (var size in new[] { new Size(850, 620), new Size(1060, 790), new Size(1280, 800) })
        {
            window.Width = size.Width; window.Height = size.Height; window.PreviewStep(2); window.UpdateLayout();
            Require(((ScrollViewer)window.FindName("PageScroll")).ActualHeight > 140, "options-scrollable-at-" + size.Width);
        }
        CheckAcceptedReview(window, events);
        return JsonSerializer.Serialize(new { passed = true, events, desktopLanguageDefaults }, new JsonSerializerOptions { WriteIndented = true });
    }
    private static List<JsonElement> CheckDesktopLanguageDefaults(List<string> events)
    {
        var original = InstallerI18n.Language;
        var defaults = new List<JsonElement>();
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); events.Add(name); }
        try
        {
            foreach (var language in new[] { "zh-CN", "en-US" })
            {
                InstallerI18n.SetLanguage(language);
                var panel = new InstallerOptionsPanel();
                Require(!panel.Children.OfType<TextBlock>().Any(x => x.Text.Contains("系统更新") || x.Text.Contains("system updates"))
                    && !panel.Describe().Contains("系统更新") && !panel.Describe().Contains("system updates"),
                    "no-system-update-pause-disclosure-" + language);
                var expected = language == "zh-CN" ? "zh_CN" : "en_US";
                Require(panel.Selection.KdeLanguage == expected && InstallerOptions.Defaults.KdeLanguage == expected,
                    "desktop-default-follows-installer-" + language);
                var selection = panel.Selection;
                InstallerOptions.Validate(selection);
                defaults.Add(JsonSerializer.SerializeToElement(selection, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower }));
                var changes = 0; panel.Changed += (_, _) => changes++;
                InstallerI18n.SetLanguage(language == "zh-CN" ? "en-US" : "zh-CN"); panel.Refresh();
                Require(panel.Selection.KdeLanguage == (language == "zh-CN" ? "en_US" : "zh_CN"),
                    "untouched-desktop-follows-language-switch-" + language);
                Require(changes == 1, "automatic-desktop-language-notifies-plan-" + language);
                changes = 0;
                foreach (var manual in new[] { "system", "zh_TW", "zh_CN", "en_US" })
                {
                    panel.KdeChoice.SelectedItem = panel.KdeChoice.Items.Cast<ComboBoxItem>().Single(x => (string)x.Tag == manual);
                    Require(changes > 0, "manual-desktop-language-notifies-plan-" + language + "-" + manual);
                    changes = 0;
                    InstallerI18n.SetLanguage("zh-CN"); panel.Refresh();
                    InstallerI18n.SetLanguage("en-US"); panel.Refresh();
                    Require(panel.Selection.KdeLanguage == manual && changes == 0,
                        "manual-desktop-language-survives-switches-" + language + "-" + manual);
                    var roundtrip = JsonSerializer.Deserialize<SelectedOptions>(JsonSerializer.Serialize(panel.Selection))!;
                    Require(roundtrip.KdeLanguage == manual, "desktop-language-roundtrip-" + language + "-" + manual);
                }
            }
        }
        finally { InstallerI18n.SetLanguage(original); }
        return defaults;
    }
    private static void CheckAcceptedReview(MainWindow window, List<string> events)
    {
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); events.Add(name); }
        var panel = (InstallerOptionsPanel)Find<StackPanel>("ComponentOptionsHost").Children[0];
        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        T Field<T>(string name) => (T)typeof(InstallerOptionsPanel).GetField(name, flags)!.GetValue(panel)!;
        var source = Path.Combine(Backend.Root, "logs", "consent-check-" + Guid.NewGuid().ToString("N") + ".img");
        File.WriteAllBytes(source, RecoveryImageChecks.Fixture());
        try
        {
            var picker = Find<PartitionPicker>("PartitionSelector");
            picker.LoadSnapshot(PartitionInventory.ExampleJson, false);
            picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().First(r => r.Space != null);
            picker.CapacityInput.Text = "64";
            Find<CheckBox>("UsePrepared").IsChecked = false;
            // Consent is independent of downloaded 3.10 resources. Keep this
            // fixture portable to a freshly extracted package with no cache.
            Find<CheckBox>("Upgrade310").IsChecked = false;
            Find<TextBox>("ImagePath").Text = source;
            var boot = (BootOptionsPanel)Find<StackPanel>("BootOptionsHost").Children[0];
            boot.InstallChoice.IsChecked = false;
            Field<CheckBox>("setDeckPassword").IsChecked = true;
            var password = Field<PasswordBox>("deckPassword");
            var confirmation = Field<PasswordBox>("deckPasswordConfirm");
            password.Password = confirmation.Password = "fixture-password";
            Click("TargetTab"); Click("NextButton"); Click("SafetyContinue"); Click("ReviewTab");
            var consent = Find<CheckBox>("PhysicalConsent"); consent.IsChecked = true;
            bool ReviewGreen() => ((SolidColorBrush)Find<TextBlock>("NavReview").Foreground).Color == Color.FromRgb(134, 239, 172);
            Require(ReviewGreen(), "valid-physical-plan-is-confirmed-before-start");
            var request = (InstallationRequest)typeof(MainWindow).GetProperty("Request", flags)!.GetValue(window)!;
            var changes = 0;
            EventHandler changed = (_, _) => changes++;
            panel.Changed += changed;
            try
            {
                panel.ClearSensitiveInputs();
                Require(password.Password.Length == 0 && confirmation.Password.Length == 0 && request.InitialDeckPassword == "fixture-password",
                    "password-ui-cleared-but-captured-request-retains-password");
                Require(changes == 0 && consent.IsChecked == true && ReviewGreen(), "internal-password-cleanup-preserves-plan-consent");
                typeof(MainWindow).GetField("operation", flags)!.SetValue(window, new CancellationTokenSource());
                window.PreviewStep(5);
                Require(ReviewGreen() && consent.IsChecked == true && !consent.IsEnabled, "accepted-review-stays-green-on-running-progress-page");
                window.FinishOperation();
                password.Password = "changed-password";
                Require(changes == 1 && consent.IsChecked != true && !ReviewGreen(), "user-password-edit-still-invalidates-plan-consent");
            }
            finally { panel.Changed -= changed; }
        }
        finally { window.FinishOperation(); File.Delete(source); }
    }
}
