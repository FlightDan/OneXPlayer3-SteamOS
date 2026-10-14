using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

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
        Require(SharedStorage.Candidates(Change((_, p) => p["guid"] = "44444444-4444-4444-4444-444444444444")).Length == 0, "duplicate-guid-excluded");
        Refuses(() => SharedStorage.Revalidate([mount], snapshot, Change((d, _) => d["serial"] = "changed-device")), "replacement-disk-refused");
        Refuses(() => SharedStorage.Revalidate([mount], snapshot, Change((_, p) => p["size"] = 97 * PartitionInventory.GiB)), "changed-partition-range-refused");
        Refuses(() => SharedStorage.ValidateSelection([mount], Change((_, p) => p["filesystem"] = "exFAT")), "reformatted-partition-refused");
        var options = new SelectedOptions(1, [], [], "zh-CN", "system", StorageMounts: [mount]);
        InstallerOptions.Validate(options);
        var payload = JsonSerializer.Serialize(options, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
        using var parsed = JsonDocument.Parse(payload);
        Require(parsed.RootElement.GetProperty("storage_mounts")[0].GetProperty("partuuid").GetString() == mount.Partuuid, "python-payload-uses-canonical-guid-and-schema");
        var results = new[] { "A", "B" }.Select(slot => JsonSerializer.SerializeToElement(new { slot, id = "shared-storage", status = "files_installed" })).ToArray();
        ComponentOutcome.Validate(results, options);
        Refuses(() => ComponentOutcome.Validate([], options), "missing-mount-result-blocks-installation");
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
        var panel = (SharedStoragePanel)Find<StackPanel>("StorageOptionsHost").Children[0];
        Click("StorageTab");
        Require(Find<StackPanel>("StoragePage").IsVisible && panel.Selection.Length == 0, "mount-page-empty-by-default");
        Require(Find<TextBlock>("NavStorage").Text.Contains("Beta · 未测试"), "mount-tab-explicit-beta-untested-label");
        panel.SkipButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(Find<StackPanel>("ReviewPage").IsVisible && window.CompletedSession == null, "skip-reaches-review-without-installing");
        picker.LoadSnapshot(PartitionInventory.ExampleJson, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().First(r => r.Space != null);
        picker.CapacityInput.Text = "64";
        Click("StorageTab");
        Require(panel.Choices.Count == 1 && panel.Selection.Length == 0, "snapshot-populates-data-only-without-auto-selecting");
        panel.Choices.Single().Value.Box.IsChecked = true;
        Click("ReviewTab");
        Require(Find<TextBlock>("ReviewLayout").Text.Contains("/mnt/shared/share-d0-p5"), "review-includes-mount-path");
        Find<RadioButton>("EnglishLanguage").IsChecked = true;
        Click("StorageTab");
        Require(panel.Selection.Length == 1 && panel.SkipButton.Content.ToString()!.StartsWith("Skip"), "language-change-preserves-selection-and-translates");
        var replaced = JsonNode.Parse(PartitionInventory.ExampleJson)!.AsArray();
        replaced[0]!["serial"] = "replacement-device";
        picker.LoadSnapshot(replaced.ToJsonString(), true);
        Click("ReviewTab");
        Require(panel.Selection.Length == 0 && !Find<TextBlock>("ReviewLayout").Text.Contains("/mnt/shared/share-d0-p5"), "changed-disk-clears-stale-mount-before-direct-review");
        Click("StorageTab"); panel.Choices.Single().Value.Box.IsChecked = true;
        panel.SkipButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(panel.Selection.Length == 0 && Find<TextBlock>("ReviewLayout").Text.Contains("Shared partitions: skipped"), "explicit-skip-clears-selection");
        Click("BackButton"); Require(Find<StackPanel>("StoragePage").IsVisible, "review-back-reaches-storage");
        Click("BackButton"); Require(Find<StackPanel>("ContentPage").IsVisible, "storage-back-reaches-contents");
        Find<RadioButton>("ChineseLanguage").IsChecked = true;
        Click("StorageTab");
        var directory = Path.Combine(Backend.Root, "logs", "shared-storage-ui"); Directory.CreateDirectory(directory);
        foreach (var size in new[] { new Size(1060, 720), new Size(800, 600) })
        {
            window.Width = size.Width; window.Height = size.Height; window.UpdateLayout();
            var root = (FrameworkElement)window.Content; root.Measure(size); root.Arrange(new Rect(size)); root.UpdateLayout();
            var next = Find<Button>("NextButton"); var point = next.TransformToAncestor(root).Transform(new Point());
            Require(point.Y >= 0 && point.Y + next.ActualHeight <= size.Height + 1, "mount-page-footer-visible-" + size.Width);
            WizardChecks.ExportSvg(root, size, Path.Combine(directory, $"mount-page-{size.Width}.svg"));
            var bitmap = new System.Windows.Media.Imaging.RenderTargetBitmap((int)size.Width, (int)size.Height, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
            bitmap.Render(root);
            var encoder = new System.Windows.Media.Imaging.PngBitmapEncoder(); encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bitmap));
            using var output = File.Create(Path.Combine(directory, $"mount-page-{size.Width}.png")); encoder.Save(output);
        }
        Require(window.CompletedSession == null, "no-installation-started-by-mount-options");
        picker.LoadSnapshot(PartitionInventory.ExampleJson, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().First(r => r.Space != null);
        picker.CapacityInput.Text = "64"; picker.AlignRight.IsChecked = true;
        Click("TargetTab");
        window.Width = 1060; window.Height = 790; window.UpdateLayout();
        var preview = (FrameworkElement)window.Content; var previewSize = new Size(1060, 790);
        preview.Measure(previewSize); preview.Arrange(new Rect(previewSize)); preview.UpdateLayout();
        picker.CapacityPanel.BringIntoView(); window.UpdateLayout();
        WizardChecks.ExportSvg(preview, previewSize, Path.Combine(directory, "right-placement.svg"));
        var placementBitmap = new System.Windows.Media.Imaging.RenderTargetBitmap(1060, 790, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
        placementBitmap.Render(preview);
        var placementEncoder = new System.Windows.Media.Imaging.PngBitmapEncoder(); placementEncoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(placementBitmap));
        using (var placementOutput = File.Create(Path.Combine(directory, "right-placement.png"))) placementEncoder.Save(placementOutput);
        return JsonSerializer.Serialize(new { passed = true, checks, previewDirectory = directory, pixelValidation = false }, new JsonSerializerOptions { WriteIndented = true });
    }
}
