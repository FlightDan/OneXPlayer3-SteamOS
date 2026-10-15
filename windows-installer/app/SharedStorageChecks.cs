using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace OxpInstaller;

internal static class SharedStorageChecks
{
    internal static string Run()
    {
        var checks = new List<string>();
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); checks.Add(name); }
        void Refuses(Action action, string name)
        {
            try { action(); } catch (IOException) { checks.Add(name); return; }
            throw new IOException("Did not refuse: " + name);
        }
        var snapshot = PartitionInventory.ExampleJson;
        var candidates = SharedStorage.Candidates(snapshot);
        Require(candidates.Length == 1 && candidates[0].Mount.MountName == "share-d0-p5", "only-ordinary-data-excludes-windows-efi-recovery");
        var mount = candidates.Single().Mount;
        SharedStorage.ValidateSelection([mount], snapshot);
        SharedStorage.Revalidate([mount], snapshot, snapshot);
        Require(SharedStorage.Candidates(null).Length == 0, "missing-inventory-is-empty");
        Refuses(() => SharedStorage.Validate([mount, mount]), "duplicate-partuuid-refused");
        Refuses(() => SharedStorage.Validate([mount with { MountName = "../../etc" }]), "mount-path-traversal-refused");
        Refuses(() => SharedStorage.Validate([mount with { Partuuid = mount.Partuuid + "\n" }]), "fstab-injection-refused");
        Refuses(() => SharedStorage.Validate([mount with { Filesystem = "auto" }]), "unapproved-filesystem-refused");
        string Change(Action<JsonObject, JsonObject> edit)
        {
            var tree = JsonNode.Parse(snapshot)!.AsArray(); var disk = tree[0]!.AsObject();
            var part = disk["partitions"]!.AsArray().Single(p => p!["number"]!.GetValue<int>() == 5)!.AsObject();
            edit(disk, part); return tree.ToJsonString();
        }
        foreach (var field in new[] { "isBoot", "isSystem", "isHidden" })
        {
            Require(SharedStorage.Candidates(Change((_, p) => p[field] = true)).Length == 0, "protected-flag-excluded-" + field);
            Require(SharedStorage.Candidates(Change((_, p) => p.Remove(field))).Length == 0, "missing-protection-flag-excluded-" + field);
        }
        foreach (var field in new[] { "isOffline", "isReadOnly" })
            Require(SharedStorage.Candidates(Change((d, _) => d.Remove(field))).Length == 0, "missing-disk-state-excluded-" + field);
        Require(SharedStorage.Candidates(Change((_, p) => p["filesystem"] = "Unknown")).Length == 0, "unknown-or-locked-volume-excluded");
        string Linux(string filesystem = "ext4", Action<JsonObject, JsonObject>? edit = null) => Change((d, p) =>
        {
            d["bus"] = "SCSI"; p["filesystem"] = filesystem; p["gptType"] = "0fc63daf-8483-4772-8e79-3d69d8477de4";
            p["filesystemSource"] = "signature"; p["sharedStorageSafe"] = true; p["isHidden"] = true;
            edit?.Invoke(d, p);
        });
        foreach (var filesystem in new[] { "ext4", "btrfs" })
        {
            var linux = Linux(filesystem);
            var linuxCandidates = SharedStorage.Candidates(linux);
            Require(linuxCandidates.Length == 1 && linuxCandidates[0].Mount.Filesystem == filesystem, "verified-linux-data-on-scsi-card-reader-" + filesystem);
            SharedStorage.ValidateSelection([linuxCandidates.Single().Mount], linux);
            Require(SharedStorage.Candidates(Linux(filesystem, (_, p) => p.Remove("sharedStorageSafe"))).Length == 0, "linux-without-native-protection-proof-excluded-" + filesystem);
            Require(SharedStorage.Candidates(Linux(filesystem, (_, p) => p["sharedStorageSafe"] = false)).Length == 0, "linux-protected-gpt-excluded-" + filesystem);
            Require(SharedStorage.Candidates(Linux(filesystem, (_, p) => p["filesystemSource"] = "windows")).Length == 0, "linux-without-readonly-signature-excluded-" + filesystem);
            Require(SharedStorage.Candidates(Linux(filesystem, (_, p) => p["gptType"] = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709")).Length == 0, "linux-root-gpt-type-excluded-" + filesystem);
            Require(SharedStorage.Candidates(Linux(filesystem, (_, p) => p["isSystem"] = true)).Length == 0, "linux-system-partition-excluded-" + filesystem);
            Require(SharedStorage.Candidates(Linux(filesystem, (_, p) => p["gptType"] = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7")).Length == 1, "verified-linux-on-basic-data-" + filesystem);
        }
        Require(SharedStorage.Candidates(Linux("LUKS")).Length == 0, "encrypted-linux-container-excluded");
        Require(SharedStorage.Candidates(Change((_, p) => p["guid"] = "44444444-4444-4444-4444-444444444444")).Length == 0, "duplicate-guid-excluded");
        Refuses(() => SharedStorage.Revalidate([mount], snapshot, Change((d, _) => d["serial"] = "changed-device")), "replacement-disk-refused");
        Refuses(() => SharedStorage.Revalidate([mount], snapshot, Change((_, p) => p["size"] = 97 * PartitionInventory.GiB)), "changed-partition-range-refused");
        Refuses(() => SharedStorage.ValidateSelection([mount], Change((_, p) => p["filesystem"] = "exFAT")), "reformatted-partition-refused");
        var options = new SelectedOptions(1, [], [], "zh-CN", "system", StorageMounts: [mount]);
        InstallerOptions.Validate(options);
        var payload = JsonSerializer.Serialize(options, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
        using var parsed = JsonDocument.Parse(payload);
        Require(parsed.RootElement.GetProperty("storage_mounts")[0].GetProperty("partuuid").GetString() == mount.Partuuid, "python-payload-uses-canonical-guid-and-schema");
        var hold = new[] { "A", "B" }.Select(slot => JsonSerializer.SerializeToElement(new {
            slot, id = "system-update-hold", status = "files_installed", os_image_updates = "held", steam_client_updates = "unchanged"
        })).ToArray();
        var results = hold.Concat(new[] { "A", "B" }.Select(slot => JsonSerializer.SerializeToElement(new { slot, id = "shared-storage", status = "files_installed" }))).ToArray();
        ComponentOutcome.Validate(results, options);
        Refuses(() => ComponentOutcome.Validate(hold, options), "missing-mount-result-blocks-installation");
        return JsonSerializer.Serialize(new { passed = true, checks }, new JsonSerializerOptions { WriteIndented = true });
    }

    internal static string RunUi(MainWindow window)
    {
        var checks = new List<string>();
        void Require(bool value, string name) { if (!value) throw new IOException(name); checks.Add(name); }
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var picker = Find<PartitionPicker>("PartitionSelector"); picker.AutomaticReadEnabled = false;
        window.WindowState = WindowState.Normal; window.ShowActivated = false; window.Show();
        Require(Find<Button>("StorageTab").Visibility == Visibility.Collapsed && !Find<Button>("StorageTab").IsEnabled,
            "mount-entry-hidden-and-disabled");
        Require(Find<StackPanel>("StorageOptionsHost").Children.Count == 0, "mount-selector-not-created");
        foreach (var language in new[] { "ChineseLanguage", "EnglishLanguage" })
        {
            Find<RadioButton>(language).IsChecked = true;
            Click("ContentTab"); Click("NextButton");
            Require(Find<StackPanel>("ReviewPage").IsVisible, "contents-next-goes-directly-to-review-" + language);
            Require(!Find<TextBlock>("ReviewLayout").Text.Contains("共享分区") && !Find<TextBlock>("ReviewLayout").Text.Contains("Shared partitions"),
                "review-omits-hidden-mount-summary-" + language);
            Click("BackButton");
            Require(Find<StackPanel>("ContentPage").IsVisible, "review-back-goes-directly-to-contents-" + language);
            window.PreviewStep(MainWindow.StorageStep);
            Require(Find<StackPanel>("ReviewPage").IsVisible && !Find<StackPanel>("StoragePage").IsVisible,
                "old-mount-step-redirects-to-review-" + language);
            Require(window.CurrentOptions.StorageMounts == null, "new-install-options-omit-mounts-" + language);
            Require(Find<TextBlock>("NavReview").Text.StartsWith("04") && Find<TextBlock>("NavResult").Text.StartsWith("07"),
                "visible-step-numbers-are-contiguous-" + language);
        }
        Find<CheckBox>("DebugMode").IsChecked = true;
        Require(Find<Button>("StorageTab").Visibility == Visibility.Collapsed, "debug-mode-does-not-reveal-mounts");
        Find<CheckBox>("DebugMode").IsChecked = false;
        checks.AddRange(WizardChecks.CheckFreeNavigation(window));
        Require(window.CompletedSession == null, "navigation-does-not-start-installation");
        Find<RadioButton>("ChineseLanguage").IsChecked = true;
        Click("ContentTab");
        var directory = Path.Combine(Backend.Root, "logs", "shared-storage-ui"); Directory.CreateDirectory(directory);
        window.Width = 1060; window.Height = 790; window.UpdateLayout();
        var root = (FrameworkElement)window.Content; var size = new Size(1060, 790);
        root.Measure(size); root.Arrange(new Rect(size)); root.UpdateLayout();
        WizardChecks.ExportSvg(root, size, Path.Combine(directory, "mount-hidden.svg"));
        var bitmap = new System.Windows.Media.Imaging.RenderTargetBitmap(1060, 790, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
        bitmap.Render(root);
        var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder(); encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
        using (var output = File.Create(Path.Combine(directory, "mount-hidden.png"))) encoder.Save(output);
        return JsonSerializer.Serialize(new { passed = true, checks, previewDirectory = directory, pixelValidation = false }, new JsonSerializerOptions { WriteIndented = true });
    }
}
