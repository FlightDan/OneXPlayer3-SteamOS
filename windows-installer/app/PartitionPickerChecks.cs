using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace OxpInstaller;

public static class PartitionPickerChecks
{
    public static string Run(string? liveSnapshot = null)
    {
        System.Windows.Media.RenderOptions.ProcessRenderMode = System.Windows.Interop.RenderMode.SoftwareOnly;
        var proof = new List<string>();
        void Require(bool result, string name) { if (!result) throw new IOException(name); proof.Add(name); }
        void Reject(Action action, string name)
        {
            var rejected = false; try { action(); } catch (InvalidOperationException) { rejected = true; }
            Require(rejected, name);
        }
        var json = PartitionInventory.ExampleJson; var disk = PartitionInventory.Read(json).Single();
        if (liveSnapshot != null)
        {
            var live = PartitionInventory.Read(File.ReadAllText(liveSnapshot));
            Require(live.Length > 0, "live-snapshot-contains-disks");
            Require(live.All(d => d.Rows.Zip(d.Rows.Skip(1)).All(p => p.First.Start + p.First.Size <= p.Second.Start)), "live-rows-ordered-and-nonoverlapping");
        }
        var gap = disk.Rows.Single(r => r.Space != null).Space!;
        var formatSelection = new PartitionSelection(json, true, gap.Disk, gap.Start, 100 * PartitionInventory.GiB);
        var formatRequest = new RemainingFormatRequest(formatSelection, "zh-CN");
        var formatPlan = RemainingSpaceFormat.Plan(formatSelection);
        Require(formatPlan.Start == gap.Start + 100 * PartitionInventory.GiB && formatPlan.Size + 100 * PartitionInventory.GiB == gap.Size && formatPlan.Start % 4096 == 0, "ntfs-tail-exact-range-and-4k-alignment");
        Reject(() => RemainingSpaceFormat.Plan(formatSelection with { Capacity = gap.Size }), "ntfs-no-remainder-refused");
        Reject(() => RemainingSpaceFormat.Plan(formatSelection with { Capacity = gap.Size - PartitionInventory.MiB }), "ntfs-too-small-refused");
        Reject(() => RemainingSpaceFormat.Simulate(formatRequest with { Selection = formatSelection with { Example = false } }), "ntfs-simulation-refuses-physical");
        var formattedExample = RemainingSpaceFormat.Simulate(formatRequest);
        RemainingSpaceFormat.ValidateFormattedSnapshot(formattedExample, true, formatRequest);
        var swappedFormat = JsonNode.Parse(formattedExample)!;
        swappedFormat[0]!["guid"] = "99999999-9999-9999-9999-999999999999";
        Reject(() => RemainingSpaceFormat.ValidateFormattedSnapshot(swappedFormat.ToJsonString(), true, formatRequest), "formatted-snapshot-disk-swap-refused");
        var changedReservation = JsonNode.Parse(formattedExample)!;
        changedReservation[0]!["partitions"]!.AsArray().Last()!["offset"] = formatPlan.Start + PartitionInventory.MiB;
        Reject(() => RemainingSpaceFormat.ValidateFormattedSnapshot(changedReservation.ToJsonString(), true, formatRequest), "formatted-snapshot-wrong-reservation-refused");
        var changedExisting = JsonNode.Parse(formattedExample)!;
        changedExisting[0]!["partitions"]!.AsArray().First()!["size"] = 259 * PartitionInventory.MiB;
        Reject(() => RemainingSpaceFormat.ValidateFormattedSnapshot(changedExisting.ToJsonString(), true, formatRequest), "formatted-snapshot-existing-partition-change-refused");
        var formattedRows = PartitionInventory.Read(formattedExample).Single().Rows;
        Require(formattedRows.Single(r => r.Space != null).Size == formatSelection.Capacity, "ntfs-keeps-steamos-reservation");
        Require(disk.Rows.Where(r => r.Type != "—").All(r => formattedRows.Contains(r)), "ntfs-keeps-existing-partitions");
        var deletable = disk.Rows.Single(r => r.CanDelete);
        var deletion = new PartitionDeleteRequest(json, true, disk.Number, deletable.Start, "zh-CN");
        var linux = JsonNode.Parse(json)!;
        var linuxPart = linux[0]!["partitions"]!.AsArray().Single(p => (int)p!["number"]! == 5)!;
        linuxPart["gptType"] = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"; linuxPart["filesystem"] = ""; linuxPart["type"] = "Unknown";
        Require(PartitionDeletion.Validate(deletion with { Snapshot = linux.ToJsonString() }).Row.CanDelete, "linux-unknown-filesystem-deletable");
        linuxPart["isHidden"] = true;
        Reject(() => PartitionDeletion.Validate(deletion with { Snapshot = linux.ToJsonString() }), "hidden-unknown-needs-native-attributes");
        linuxPart["nativeUnrecognizedSafe"] = true;
        Require(PartitionDeletion.Validate(deletion with { Snapshot = linux.ToJsonString() }).Row.CanDelete, "linux-synthetic-hidden-with-clear-native-attributes-deletable");
        foreach (var protectedType in new[] { "C12A7328-F81F-11D2-BA4B-00A0C93EC93B", "E3C9E316-0B5C-4DB8-817D-F92DF00215AE", "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC", "21686148-6449-6E6F-744E-656564454649" })
        {
            linuxPart["gptType"] = protectedType;
            Reject(() => PartitionDeletion.Validate(deletion with { Snapshot = linux.ToJsonString() }), "unknown-still-protects-type-" + protectedType);
        }
        var simulated = PartitionDeletion.Simulate(deletion);
        var released = PartitionInventory.Read(simulated).Single();
        Require(released.Rows.Single(r => r.Space != null).Size == gap.Size + deletable.Size, "delete-merges-adjacent-unallocated-space");
        Require(released.Rows.Where(r => r.Type != "—").SequenceEqual(disk.Rows.Where(r => r.Type != "—" && !r.CanDelete)), "delete-keeps-all-other-partitions");
        Reject(() => PartitionDeletion.Simulate(deletion with { Example = false }), "real-layout-cannot-be-simulated");
        foreach (var protectedRow in disk.Rows.Where(r => r.Type != "—" && !r.CanDelete))
            Reject(() => PartitionDeletion.Validate(deletion with { Start = protectedRow.Start }), "protect-system-partition-" + protectedRow.Name);
        foreach (var key in new[] { "isBoot", "isSystem", "isHidden" })
        {
            var changed = JsonNode.Parse(json)!;
            changed[0]!["partitions"]!.AsArray().Single(p => (int)p!["number"]! == 5)![key] = true;
            Reject(() => PartitionDeletion.Validate(deletion with { Snapshot = changed.ToJsonString() }), "deletion-blocks-" + key);
        }
        var missingProtection = JsonNode.Parse(json)!;
        missingProtection[0]!["partitions"]!.AsArray().Single(p => (int)p!["number"]! == 5)!.AsObject().Remove("deletionAllowed");
        Reject(() => PartitionDeletion.Validate(deletion with { Snapshot = missingProtection.ToJsonString() }), "deletion-missing-protection-fails-closed");
        PartitionSelection Plan(long bytes) => new(json, true, gap.Disk, gap.Start, bytes);
        foreach (var capacity in new[] { PartitionInventory.Minimum, 100 * PartitionInventory.GiB, 128 * PartitionInventory.GiB, gap.Size })
        {
            var plan = Plan(capacity); var after = PartitionInventory.After(plan); var before = PartitionInventory.Before(disk);
            Require(after.Where(s => s.Action == "new").Sum(s => s.Size) == capacity, "new-partitions-exact-capacity-" + capacity);
            Require(after.Sum(s => s.Size) == before.Sum(s => s.Size), "total-space-conserved-" + capacity);
            Require(after.Where(s => s.Action == "keep").SequenceEqual(before.Where(s => s.Action == "keep")), "existing-partitions-identical-" + capacity);
            Require(after.Zip(after.Skip(1)).All(p => p.First.Start + p.First.Size <= p.Second.Start), "no-overlap-" + capacity);
        }
        foreach (var input in new[] { "", "NaN", "-1", "63.999", "999999999999999999999999999", "1e3", "128,5" })
            Reject(() => PartitionInventory.ParseCapacity(input, gap.Size), "reject-invalid-input-" + input);
        Reject(() => Plan(gap.Size + PartitionInventory.MiB).Target(), "reject-over-capacity");
        Reject(() => Plan(PartitionInventory.Minimum - 1).Target(), "reject-below-minimum");
        Reject(() => Plan(PartitionInventory.Minimum + 1).Target(), "reject-unaligned");
        Reject(() => (Plan(PartitionInventory.Minimum) with { Start = PartitionInventory.MiB }).Target(), "reject-existing-partition");
        var saved = JsonSerializer.Deserialize<PartitionSelection>(JsonSerializer.Serialize(Plan(128 * PartitionInventory.GiB)))!;
        Require(saved.Target().Size == 128 * PartitionInventory.GiB && saved.Example, "selection-json-roundtrip");
        foreach (var (key, value) in new (string, JsonNode?)[] { ("isReadOnly", JsonValue.Create(true)), ("isOffline", JsonValue.Create(true)), ("style", JsonValue.Create("MBR")), ("sectorSize", JsonValue.Create(4096)), ("bus", JsonValue.Create("Spaces")), ("guid", JsonValue.Create("")) })
        {
            var changed = JsonNode.Parse(json)!; changed[0]![key] = value;
            Require(PartitionInventory.Read(changed.ToJsonString()).Single().Rows.All(r => r.Space == null), "unselectable-" + key);
        }
        InstallerI18n.SetLanguage("zh-CN");
        var window = new MainWindow(rehearsal: true) { ShowActivated = false, WindowState = WindowState.Normal };
        ((PartitionPicker)window.FindName("PartitionSelector")).AutomaticReadEnabled = false;
        window.Show();
        T Find<T>(string name) => (T)window.FindName(name);
        void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        var picker = Find<PartitionPicker>("PartitionSelector");
        Require(picker.AlignRight.IsChecked == true && picker.AlignLeft.IsChecked != true, "new-picker-defaults-to-right-placement");
        picker.LoadSnapshot(json, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        Require(picker.Selection.AlignRight && picker.Selection.Target().Start + picker.Selection.Capacity == gap.Start + gap.Size,
            "default-selection-reserves-right-end-of-gap");
        Require(picker.FormatRemainingButton.Visibility == Visibility.Visible && picker.FormatRemainingHint.Visibility == Visibility.Visible
            && !picker.FormatRemainingButton.Content.ToString()!.Contains("未测试"), "ntfs-tested-entry-visible");
        picker.SelectReservedSpace(formattedExample, true, formatRequest);
        Require(picker.Selection.Capacity == formatSelection.Capacity && !picker.FormatRemainingButton.IsEnabled, "formatted-layout-reselected-and-repeat-disabled");
        var large = JsonNode.Parse(json)!;
        large[0]!["partitions"]!.AsArray().Single(p => (int)p!["number"]! == 4)!["offset"] = gap.Start + 500 * PartitionInventory.GiB;
        large[0]!["size"] = gap.Start + 500 * PartitionInventory.GiB + 513 * PartitionInventory.MiB;
        var largeRequest = new RemainingFormatRequest(new PartitionSelection(large.ToJsonString(), true, gap.Disk, gap.Start, 64 * PartitionInventory.GiB), "zh-CN");
        picker.SelectReservedSpace(RemainingSpaceFormat.Simulate(largeRequest), true, largeRequest);
        Require(picker.Selection.Capacity == 64 * PartitionInventory.GiB && picker.Selection.Target().Size == 64 * PartitionInventory.GiB
            && !picker.FormatRemainingButton.IsEnabled, "500g-gap-64g-format-reserves-installation-and-disables-repeat");
        picker.LoadSnapshot(json, false);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.CapacityInput.Text = "100";
        Require(!picker.FormatRemainingButton.IsEnabled, "rehearsal-blocks-real-formatting");
        picker.LoadSnapshot(json, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.CapacityInput.Text = "100";
        Require(picker.FormatRemainingButton.IsEnabled, "example-with-remainder-enables-formatting");
        picker.LoadSnapshot(json, true);
        Click("NextButton");
        Require(Find<StackPanel>("TargetPage").Visibility == Visibility.Visible && Find<TextBlock>("ValidationMessage").Text.Length > 0, "next-requires-target");
        picker.LoadSnapshot(json, true);
        picker.Partitions.SelectedIndex = 0;
        Require(!picker.DeletePartitionButton.IsEnabled, "protected-row-disables-delete");
        Reject(() => _ = picker.Selection, "existing-row-cannot-be-selected-as-target");
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.CanDelete);
        Require(picker.DeletePartitionButton.IsEnabled, "example-data-partition-enables-delete");
        picker.SelectReleasedSpace(simulated, true, deletion);
        Require(picker.Selection.Start == deletable.Start && !picker.DeletePartitionButton.IsEnabled, "after-delete-selects-merged-gap-and-disables-delete");
        picker.LoadSnapshot(json, false);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.CanDelete);
        Require(!picker.DeletePartitionButton.IsEnabled, "rehearsal-blocks-real-deletion");
        picker.LoadSnapshot(json, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.CapacityInput.Text = "128";
        Require(picker.Selection.Capacity == 128 * PartitionInventory.GiB, "capacity-input-updates-selection");
        picker.Capacity64Button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(picker.Selection.Capacity == 64 * PartitionInventory.GiB, "64g-preset-updates-plan");
        Require(picker.AlignLeft.IsChecked == true && !picker.Selection.AlignRight, "restored-left-selection-keeps-placement");
        picker.AlignRight.IsChecked = true;
        Require(picker.Selection.AlignRight && picker.Selection.Target().Start == gap.Start + gap.Size - picker.Selection.Capacity,
            "right-placement-puts-steamos-at-gap-end");
        var rightRequest = new RemainingFormatRequest(picker.Selection, "zh-CN");
        var rightFormatted = RemainingSpaceFormat.Simulate(rightRequest);
        picker.SelectReservedSpace(rightFormatted, true, rightRequest);
        Require(picker.Selection.AlignRight && picker.Selection.Capacity == 64 * PartitionInventory.GiB
            && picker.Selection.Target().Start == rightRequest.Selection.Target().Start && !picker.FormatRemainingButton.IsEnabled,
            "right-ntfs-format-reselects-exact-reserved-tail");
        picker.RefreshLanguage();
        Require(picker.Selection.AlignRight, "language-refresh-preserves-right-placement");
        picker.LoadSnapshot(json, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.AlignLeft.IsChecked = true;
        picker.Capacity100Button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        Require(picker.Selection.Capacity == 100 * PartitionInventory.GiB, "100g-preset-updates-plan");
        var small = JsonNode.Parse(json)!;
        small[0]!["partitions"]!.AsArray().Single(p => (int)p!["number"]! == 4)!["offset"] = gap.Start + 96 * PartitionInventory.GiB;
        small[0]!["size"] = gap.Start + 96 * PartitionInventory.GiB + 513 * PartitionInventory.MiB;
        picker.LoadSnapshot(small.ToJsonString(), true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        Require(!picker.Capacity100Button.IsEnabled && picker.Capacity64Button.IsEnabled, "insufficient-space-disables-only-100g");
        picker.LoadSnapshot(json, true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.CapacityInput.Text = "32"; Click("NextButton");
        Require(Find<StackPanel>("TargetPage").Visibility == Visibility.Visible && picker.ChangesHost.Children.Count == 0, "invalid-capacity-blocks-next-and-clears-preview");
        Require(picker.AllSpaceButton.Visibility == Visibility.Collapsed && !picker.AllSpaceButton.IsVisible,
            "use-all-entry-is-hidden");
        picker.CapacityInput.Text = "128.5";
        Require(picker.Selection.Capacity == 128 * PartitionInventory.GiB + 512 * PartitionInventory.MiB, "fractional-gib-supported");
        Click("NextButton"); Require(Find<StackPanel>("SourcePage").Visibility == Visibility.Visible, "valid-target-reaches-source");
        Click("BackButton"); Require(picker.CapacityInput.Text == "128.5", "back-retains-selection");
        Find<RadioButton>("EnglishLanguage").IsChecked = true;
        Require(picker.Selection.Capacity == 128 * PartitionInventory.GiB + 512 * PartitionInventory.MiB && picker.Heading.Text == "Choose disk and installation space", "language-switch-preserves-selection");
        Require(!picker.FormatRemainingButton.Content.ToString()!.Contains("Untested") && !picker.FormatRemainingHint.Text.Contains("Untested on hardware"), "ntfs-english-tested-entry");
        Find<RadioButton>("ChineseLanguage").IsChecked = true;
        window.PreviewStep(3);
        Require(Find<StackPanel>("ReviewPartitionHost").Children.Count > 5, "review-renders-selected-plan");
        Find<RadioButton>("ExternalTarget").IsChecked = true; window.PreviewStep(3);
        Require(Find<Border>("ReviewPartitionCard").Visibility == Visibility.Collapsed, "external-does-not-reuse-shared-plan");
        Find<RadioButton>("InternalTarget").IsChecked = true;
        var second = JsonNode.Parse(json)!; var other = second[0]!.DeepClone(); other["number"] = 1; other["guid"] = "66666666-6666-6666-6666-666666666666"; second.AsArray().Add(other);
        picker.LoadSnapshot(second.ToJsonString(), true);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.Disks.SelectedIndex = 1;
        Reject(() => _ = picker.Selection, "disk-change-invalidates-region-and-capacity");
        picker.LoadSnapshot(json, true);
        Reject(() => _ = picker.Selection, "refresh-invalidates-old-selection");
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.CapacityInput.Text = "128";
        var directory = Path.Combine(Backend.Root, "logs", "partition-picker-" + DateTime.Now.ToString("yyyyMMdd-HHmmss")); Directory.CreateDirectory(directory);
        window.PreviewStep(0); window.UpdateLayout();
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.CanDelete);
        picker.DeletePartitionButton.BringIntoView(); window.UpdateLayout();
        Require(picker.DeletePartitionButton.ActualHeight >= 48, "delete-button-touch-target");
        var entryRoot = (FrameworkElement)window.Content;
        var entryImage = new RenderTargetBitmap((int)entryRoot.ActualWidth, (int)entryRoot.ActualHeight, 96,96,PixelFormats.Pbgra32); entryImage.Render(entryRoot);
        var entryEncoder = new PngBitmapEncoder(); entryEncoder.Frames.Add(BitmapFrame.Create(entryImage));
        using (var stream = File.Create(Path.Combine(directory,"delete-entry.png"))) entryEncoder.Save(stream);
        picker.Partitions.SelectedItem = picker.Partitions.Items.Cast<PartitionRow>().Single(r => r.Space != null);
        picker.CapacityInput.Text = "128";
        foreach (var language in new[] { "zh-CN", "en-US" })
        {
            InstallerI18n.SetLanguage(language);
            var formatDialog = RemainingSpaceFormat.Confirmation(formatRequest with { Language = language });
            Require(!formatDialog.Title.Contains(language == "en-US" ? "Untested" : "未测试"), "ntfs-confirmation-tested-" + language);
            formatDialog.ShowActivated = false; formatDialog.MaxHeight = 540; formatDialog.Show(); formatDialog.UpdateLayout();
            var formatPanel = (StackPanel)((ScrollViewer)formatDialog.Content).Content;
            var formatConsent = formatPanel.Children.OfType<CheckBox>().Single();
            var formatButtons = formatPanel.Children.OfType<WrapPanel>().Single().Children.OfType<Button>().ToArray();
            Require(formatButtons[0].IsDefault && formatButtons[0].IsCancel && !formatButtons[1].IsEnabled, "format-default-cancel-"+language);
            formatConsent.IsChecked=true; Require(formatButtons[1].IsEnabled, "format-explicit-consent-"+language);
            formatConsent.IsChecked=false; Require(!formatButtons[1].IsEnabled, "format-unchecked-consent-blocks-"+language);
            var formatRoot=(FrameworkElement)formatDialog.Content;
            var formatBitmap=new RenderTargetBitmap((int)Math.Ceiling(formatRoot.ActualWidth),(int)Math.Ceiling(formatRoot.ActualHeight),96,96,PixelFormats.Pbgra32);formatBitmap.Render(formatRoot);
            var formatEncoder=new PngBitmapEncoder();formatEncoder.Frames.Add(BitmapFrame.Create(formatBitmap));
            using(var stream=File.Create(Path.Combine(directory,"format-confirmation-"+language+".png")))formatEncoder.Save(stream);
            formatDialog.Close();
            var dialog = PartitionDeletion.Confirmation(deletion with { Language = language, Example = false });
            dialog.ShowActivated = false; dialog.MaxHeight = 540; dialog.Show(); dialog.UpdateLayout();
            var panel = (StackPanel)((ScrollViewer)dialog.Content).Content;
            var consent = panel.Children.OfType<CheckBox>().Single();
            var buttons = panel.Children.OfType<WrapPanel>().Single().Children.OfType<Button>().ToArray();
            Require(buttons[0].IsCancel && buttons[0].IsDefault && !buttons[1].IsDefault && !buttons[1].IsEnabled, "deletion-default-is-cancel-" + language);
            consent.IsChecked = true; Require(buttons[1].IsEnabled, "deletion-requires-explicit-consent-" + language);
            consent.IsChecked = false; Require(!buttons[1].IsEnabled, "unchecked-consent-disables-deletion-" + language);
            var root = (FrameworkElement)dialog.Content;
            var bmp = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth), (int)Math.Ceiling(root.ActualHeight), 96,96,PixelFormats.Pbgra32); bmp.Render(root);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bmp));
            using (var stream = File.Create(Path.Combine(directory,"delete-confirmation-" + language + ".png"))) encoder.Save(stream);
            dialog.Close();
        }
        InstallerI18n.SetLanguage("zh-CN");
        foreach (var size in new[] { new Size(1060,790), new Size(850,620) })
        {
            window.Width = size.Width; window.Height = size.Height;
            foreach (var step in new[] { 0,3 })
            {
                window.PreviewStep(step); window.UpdateLayout();
                var root = (FrameworkElement)window.Content; root.Measure(size); root.Arrange(new Rect(size)); root.UpdateLayout();
                if (step == 0) { picker.BringIntoView(); window.UpdateLayout(); }
                var next = Find<Button>("NextButton"); var pos = next.TransformToAncestor(root).Transform(new Point());
                Require(pos.Y + next.ActualHeight <= size.Height && pos.X + next.ActualWidth <= size.Width, $"footer-visible-{size.Width}-step-{step}");
                WizardChecks.ExportSvg(root, size, Path.Combine(directory, $"layout-{size.Width}-step-{step}.svg"));
                if (size.Width == 1060)
                {
                    var bmp = new RenderTargetBitmap((int)size.Width,(int)size.Height,96,96,PixelFormats.Pbgra32);
                    var background = new DrawingVisual();
                    using (var context = background.RenderOpen()) context.DrawRectangle(window.Background,null,new Rect(size));
                    bmp.Render(background); bmp.Render(root);
                    var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bmp));
                    using var stream = File.Create(Path.Combine(directory,$"native-step-{step}.png")); encoder.Save(stream);
                    if (step == 0)
                    {
                        picker.CapacityPanel.BringIntoView(); window.UpdateLayout();
                        var lower = new RenderTargetBitmap((int)size.Width,(int)size.Height,96,96,PixelFormats.Pbgra32); lower.Render(background); lower.Render(root);
                        var lowerEncoder = new PngBitmapEncoder(); lowerEncoder.Frames.Add(BitmapFrame.Create(lower));
                        using var lowerStream = File.Create(Path.Combine(directory,"capacity.png")); lowerEncoder.Save(lowerStream);
                    }
                }
            }
        }
        File.WriteAllText(Path.Combine(directory,"checks.json"), JsonSerializer.Serialize(new { passed = true, proof, scope = "Read-only planning and real WPF control/navigation checks. No disk writes or installation performed." }, new JsonSerializerOptions { WriteIndented = true }));
        window.Close(); return directory;
    }
}
