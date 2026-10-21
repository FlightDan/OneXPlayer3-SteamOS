using System.Buffers.Binary;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace OxpInstaller;

internal static class RecoveryImageChecks
{
    // A small GPT disk, not an installable OS. Both GPT copies use standard
    // CRC32; real recovery/root images are checked separately when present.
    internal static byte[] Fixture()
    {
        var disk = new byte[2 * 1024 * 1024];
        disk[510] = 0x55; disk[511] = 0xaa; disk[450] = 0xee;
        var header = disk.AsSpan(512, 512);
        "EFI PART"u8.CopyTo(header);
        BinaryPrimitives.WriteUInt32LittleEndian(header[8..], 0x10000);
        BinaryPrimitives.WriteUInt32LittleEndian(header[12..], 92);
        BinaryPrimitives.WriteUInt64LittleEndian(header[24..], 1);
        BinaryPrimitives.WriteUInt64LittleEndian(header[32..], (ulong)(disk.Length / 512 - 1));
        BinaryPrimitives.WriteUInt64LittleEndian(header[40..], 34);
        BinaryPrimitives.WriteUInt64LittleEndian(header[48..], (ulong)(disk.Length / 512 - 34));
        Guid.NewGuid().TryWriteBytes(header[56..]);
        BinaryPrimitives.WriteUInt64LittleEndian(header[72..], 2);
        BinaryPrimitives.WriteUInt32LittleEndian(header[80..], 128);
        BinaryPrimitives.WriteUInt32LittleEndian(header[84..], 128);
        var roles = new[] { "esp", "efi-A", "rootfs-A", "var-A", "home" };
        for (var i = 0; i < roles.Length; i++)
        {
            var entry = disk.AsSpan(1024 + i * 128, 128);
            Guid.NewGuid().TryWriteBytes(entry); Guid.NewGuid().TryWriteBytes(entry[16..]);
            BinaryPrimitives.WriteUInt64LittleEndian(entry[32..], (ulong)(40 + i * 128));
            BinaryPrimitives.WriteUInt64LittleEndian(entry[40..], (ulong)(167 + i * 128));
            Encoding.Unicode.GetBytes(roles[i]).CopyTo(entry[56..]);
        }
        Checksums(disk);
        disk.AsSpan(1024, 16384).CopyTo(disk.AsSpan(disk.Length - 33 * 512));
        header.CopyTo(disk.AsSpan(disk.Length - 512));
        var backup = disk.AsSpan(disk.Length - 512);
        BinaryPrimitives.WriteUInt64LittleEndian(backup[24..], (ulong)(disk.Length / 512 - 1));
        BinaryPrimitives.WriteUInt64LittleEndian(backup[32..], 1);
        BinaryPrimitives.WriteUInt64LittleEndian(backup[72..], (ulong)(disk.Length / 512 - 33));
        backup.Slice(16, 4).Clear(); BinaryPrimitives.WriteUInt32LittleEndian(backup[16..], Crc(backup[..92]));
        return disk;
    }

    private static uint Crc(ReadOnlySpan<byte> data)
    {
        var table = new uint[256];
        for (uint i = 0; i < table.Length; i++)
        {
            var value = i;
            for (var j = 0; j < 8; j++) value = (value & 1) != 0 ? 0xedb88320u ^ (value >> 1) : value >> 1;
            table[i] = value;
        }
        uint result = 0xffffffff;
        foreach (var value in data) result = table[(result ^ value) & 255] ^ (result >> 8);
        return result ^ 0xffffffff;
    }

    private static void Checksums(byte[] disk)
    {
        BinaryPrimitives.WriteUInt32LittleEndian(disk.AsSpan(600), Crc(disk.AsSpan(1024, 16384)));
        disk.AsSpan(528, 4).Clear();
        BinaryPrimitives.WriteUInt32LittleEndian(disk.AsSpan(528), Crc(disk.AsSpan(512, 92)));
    }

    internal static async Task<string> RunAsync(MainWindow window)
    {
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "recovery-image-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Require(bool value, string label) { if (!value) throw new IOException(label); checks.Add(label); }
        string Write(string name, byte[] bytes) { var path = Path.Combine(directory, name); File.WriteAllBytes(path, bytes); return path; }
        void Refuse(Action action, string label, string contains = "GPT")
        {
            try { action(); }
            catch (IOException error) when (error.Message.Contains(contains)) { checks.Add(label); return; }
            throw new IOException("Expected rejection: " + label);
        }
        async Task RefuseAsync(Func<Task> action, string label)
        {
            try { await action(); }
            catch (IOException error) when (error.Message.Contains("rootfs.img")) { checks.Add(label); return; }
            throw new IOException("Expected rootfs rejection: " + label);
        }
        var originalLanguage = InstallerI18n.Language;
        var root = new byte[128 * 1024]; "_BHRfS_M"u8.CopyTo(root.AsSpan(0x10040));
        var rootPath = Write("renamed-system.img", root);
        var good = Write("recovery.img", Fixture());
        var goodRenamed = Write("rootfs.img", Fixture());
        try
        {
            RecoveryImage.ValidateRaw(good); RecoveryImage.ValidateRaw(goodRenamed);
            checks.Add("valid-recovery-layout-accepted-regardless-of-filename");
            foreach (var language in new[] { "zh-CN", "en-US" })
            {
                InstallerI18n.SetLanguage(language);
                Refuse(() => RecoveryImage.ValidateRaw(rootPath), "renamed-btrfs-root-rejected-" + language, "rootfs.img");
                Refuse(() => InstallationController.ValidateRequest(new(InstallationTargetKind.ExternalDisk, rootPath, false, UpgradeTo310: true)),
                    "controller-rejects-root-before-official-source-or-installation-" + language, "rootfs.img");
            }
            InstallerI18n.SetLanguage("en-US");
            foreach (var length in new[] { 0, 1000, 8192, 17409 })
                Refuse(() => RecoveryImage.ValidateRaw(Write("truncated-" + length + ".img", new byte[length])), "truncated-or-unaligned-image-" + length);
            void Mutate(string label, Action<byte[]> change, bool checksum = true)
            {
                var bytes = Fixture(); change(bytes); if (checksum) Checksums(bytes);
                Refuse(() => RecoveryImage.ValidateRaw(Write(label + ".img", bytes)), label);
            }
            Mutate("bad-header-crc", bytes => bytes[568] ^= 1, false);
            Mutate("bad-table-crc", bytes => bytes[1100] ^= 1, false);
            Mutate("wrong-role", bytes => bytes[1024 + 56] = (byte)'x');
            Mutate("unrelated-gpt", bytes => bytes.AsSpan(1024, 16384).Clear());
            Mutate("partition-overlap", bytes => BinaryPrimitives.WriteUInt64LittleEndian(bytes.AsSpan(1024 + 128 + 32), 40));
            Mutate("partition-past-disk", bytes => BinaryPrimitives.WriteUInt64LittleEndian(bytes.AsSpan(1024 + 40), ulong.MaxValue));
            Mutate("table-offset-overflow", bytes => BinaryPrimitives.WriteUInt64LittleEndian(bytes.AsSpan(584), ulong.MaxValue));
            Mutate("table-count-overflow", bytes => BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(592), uint.MaxValue));
            Mutate("duplicate-partition-id", bytes => bytes.AsSpan(1040, 16).CopyTo(bytes.AsSpan(1040 + 128)));
            var realRecovery = Path.Combine(InstallerWorkspace.DirectoryPath, "source/steamdeck-oobe-repair-20260707.10-3.8.14.img");
            if (File.Exists(realRecovery)) { RecoveryImage.ValidateRaw(realRecovery); checks.Add("real-official-recovery-accepted"); }
            var realRoot = Path.Combine(InstallerWorkspace.DirectoryPath, "steamos-3.10/rootfs.img");
            if (File.Exists(realRoot)) Refuse(() => RecoveryImage.ValidateRaw(realRoot), "real-5-GiB-system-root-rejected", "rootfs.img");

            await RefuseAsync(async () => { await Backend.ImportAsync(rootPath, _ => { }, CancellationToken.None); }, "raw-import-rejects-root");
            var before = Directory.GetDirectories(InstallerWorkspace.DirectoryPath, "*-upgrade-source").Length;
            await RefuseAsync(async () => { await OfficialSystem.PrepareAsync(rootPath, directory, _ => { }, CancellationToken.None); }, "preparation-rejects-before-download-and-conversion");
            await RefuseAsync(async () => { await Backend.GuestAsync("upgrade-source", rootPath, true, _ => { }, CancellationToken.None, updateRoot: rootPath); }, "direct-guest-entry-rejects-before-startup");
            Require(before == Directory.GetDirectories(InstallerWorkspace.DirectoryPath, "*-upgrade-source").Length
                && !File.Exists(Path.Combine(directory, "recovery-3.10.img")), "invalid-source-created-no-guest-task-or-staging-image");
            foreach (var format in new[] { "zip", "bzip2" })
            foreach (var valid in new[] { false, true })
            {
                var input = valid ? good : rootPath;
                var archive = Path.Combine(directory, (valid ? "valid" : "root") + ".img." + (format == "zip" ? "zip" : "bz2"));
                await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/archive/7z.exe"), ["a", "-t" + format, archive, input], _ => { }, CancellationToken.None);
                if (valid)
                {
                    var imported = await Backend.ImportAsync(archive, _ => { }, CancellationToken.None);
                    RecoveryImage.ValidateRaw(imported); checks.Add("valid-compressed-recovery-import-" + format);
                }
                else await RefuseAsync(async () => { await Backend.ImportAsync(archive, _ => { }, CancellationToken.None); }, "compressed-root-rejected-after-extraction-" + format);
            }
            T Find<T>(string name) => (T)window.FindName(name);
            void Click(string name) => Find<Button>(name).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Find<PartitionPicker>("PartitionSelector").AutomaticReadEnabled = false;
            window.PreviewStep(1); Find<CheckBox>("UsePrepared").IsChecked = false;
            foreach (var language in new[] { "ChineseLanguage", "EnglishLanguage" })
            {
                InstallerI18n.SetLanguage(language == "ChineseLanguage" ? "zh-CN" : "en-US");
                Find<RadioButton>(language).IsChecked = true; Click("RecoverySourceTab");
                Find<TextBox>("ImagePath").Text = rootPath; Click("NextButton");
                var message = Find<TextBlock>("ValidationMessage").Text;
                Require(Find<StackPanel>("RecoverySourceSection").Visibility == Visibility.Visible
                    && Find<StackPanel>("OfficialSourceSection").Visibility != Visibility.Visible
                    && message.Contains("rootfs.img") && message.Contains(language == "ChineseLanguage" ? "3.10 镜像" : "3.10 image"),
                    "wizard-stays-on-recovery-with-actionable-error-" + language + ": " + message);
                Find<TextBox>("ImagePath").Text = good; Click("NextButton");
                Require(Find<StackPanel>("OfficialSourceSection").Visibility == Visibility.Visible
                    && Find<TextBlock>("ValidationMessage").Text.Length == 0, "valid-recovery-advances-to-310-" + language);
            }
            return JsonSerializer.Serialize(new { passed = true, checks, directory, physical_disk_writes = false, guest_started = false }, new JsonSerializerOptions { WriteIndented = true });
        }
        finally { InstallerI18n.SetLanguage(originalLanguage); }
    }
}
