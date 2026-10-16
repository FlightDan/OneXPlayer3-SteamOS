using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public sealed record StorageMount(string Partuuid, string Filesystem, string MountName,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)] bool SteamLibrary = false);
internal sealed record StorageCandidate(StorageMount Mount, string Title, string DiskGuid, string Serial,
    long DiskSize, long Start, long Size);

internal static class SharedStorage
{
    private const string BasicData = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7";
    private const string LinuxData = "0fc63daf-8483-4772-8e79-3d69d8477de4";
    internal static string MountPath(StorageMount mount) => "/mnt/shared/" + mount.MountName;
    internal static string SteamLibraryPath(StorageMount mount) => "/var/mnt/steam-libraries/" + mount.MountName;
    private static bool SamePartition(StorageMount left, StorageMount right) =>
        (left with { SteamLibrary = false }) == (right with { SteamLibrary = false });
    internal static void Validate(StorageMount[]? mounts)
    {
        if (mounts == null) return;
        if (mounts.Length > 32 || mounts.Any(m => m == null
            || !Guid.TryParseExact(m.Partuuid, "D", out var guid) || guid == Guid.Empty || guid.ToString("D") != m.Partuuid
            || m.Filesystem is not ("ntfs" or "exfat" or "vfat" or "ext4" or "btrfs")
            || m.SteamLibrary && m.Filesystem != "ntfs"
            || m.MountName == null || !Regex.IsMatch(m.MountName, @"\Ashare-d(?:0|[1-9][0-9]{0,4})-p[1-9][0-9]{0,4}\z"))
            || mounts.Select(m => m.Partuuid).Distinct().Count() != mounts.Length
            || mounts.Select(m => m.MountName).Distinct().Count() != mounts.Length)
            throw new IOException(PartitionInventory.L("共享分区选项无效，请重新选择。", "Invalid shared partition selection. Select the partitions again."));
    }
    internal static StorageCandidate[] Candidates(string? snapshot)
    {
        if (snapshot == null) return [];
        using var doc = JsonDocument.Parse(snapshot);
        static string Str(JsonElement item, string key) => item.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
        static bool ExplicitFalse(JsonElement item, string key) => item.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.False;
        static bool ExplicitTrue(JsonElement item, string key) => item.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.True;
        static string Id(string text) => Guid.TryParse(text, out var guid) && guid != Guid.Empty ? guid.ToString("D") : "";
        var allIds = doc.RootElement.EnumerateArray().SelectMany(d => d.GetProperty("partitions").EnumerateArray())
            .Select(p => Id(Str(p, "guid"))).ToArray();
        var result = new List<StorageCandidate>();
        foreach (var disk in doc.RootElement.EnumerateArray())
        {
            var diskGuid = Id(Str(disk, "guid"));
            if (Str(disk, "style") != "GPT" || diskGuid.Length == 0 || !ExplicitFalse(disk, "isOffline") || !ExplicitFalse(disk, "isReadOnly")
                || Str(disk, "partitionReadError").Length > 0) continue;
            var number = disk.GetProperty("number").GetInt32();
            var diskSize = disk.GetProperty("size").GetInt64();
            foreach (var part in disk.GetProperty("partitions").EnumerateArray())
            {
                var id = Id(Str(part, "guid"));
                var filesystem = Str(part, "filesystem").ToUpperInvariant() switch { "NTFS" => "ntfs", "EXFAT" => "exfat", "FAT32" => "vfat", "EXT4" => "ext4", "BTRFS" => "btrfs", _ => "" };
                var linux = filesystem is "ext4" or "btrfs";
                var type = Id(Str(part, "gptType"));
                var safeData = linux
                    ? type is BasicData or LinuxData && Str(part, "filesystemSource") == "signature" && ExplicitTrue(part, "sharedStorageSafe")
                    : type == BasicData && ExplicitFalse(part, "isHidden");
                if (id.Length == 0 || allIds.Count(value => value == id) != 1 || filesystem.Length == 0
                    || !safeData || !ExplicitFalse(part, "isBoot") || !ExplicitFalse(part, "isSystem")) continue;
                var partition = part.GetProperty("number").GetInt32();
                var start = part.GetProperty("offset").GetInt64(); var size = part.GetProperty("size").GetInt64();
                if (number < 0 || number > 99999 || partition < 1 || partition > 99999 || start < 0 || size <= 0 || start > diskSize - size) continue;
                var mount = new StorageMount(id, filesystem, $"share-d{number}-p{partition}");
                var letter = Str(part, "letter").Trim('\0'); var label = Str(part, "label");
                var title = PartitionInventory.L($"磁盘 {number} · 分区 {partition}", $"Disk {number} · Partition {partition}")
                    + (letter.Length == 1 ? $" · {letter}:" : "") + (label.Length > 0 ? " · " + label : "")
                    + $" · {Str(part, "filesystem")} · {PartitionInventory.SizeText(size)}";
                result.Add(new(mount, title, diskGuid, Str(disk, "serial"), diskSize, start, size));
            }
        }
        return result.ToArray();
    }
    internal static void ValidateSelection(StorageMount[]? mounts, string? snapshot)
    {
        Validate(mounts);
        if (mounts is not { Length: > 0 }) return;
        var candidates = Candidates(snapshot);
        if (mounts.Any(m => !candidates.Any(c => SamePartition(c.Mount, m))))
            throw new IOException(PartitionInventory.L("所选共享分区已变化或不可挂载。请返回安装位置刷新磁盘，再重新选择。", "A selected shared partition changed or is unavailable. Refresh disks at Installation location, then select it again."));
    }
    internal static void Revalidate(StorageMount[] mounts, string original, string fresh)
    {
        ValidateSelection(mounts, original); ValidateSelection(mounts, fresh);
        var before = Candidates(original); var after = Candidates(fresh);
        foreach (var mount in mounts)
        {
            var a = before.Single(c => SamePartition(c.Mount, mount)); var b = after.Single(c => SamePartition(c.Mount, mount));
            if (a.DiskGuid != b.DiskGuid || a.Serial != b.Serial || a.DiskSize != b.DiskSize || a.Start != b.Start || a.Size != b.Size)
                throw new IOException(PartitionInventory.L("共享分区所在磁盘或范围已变化，请刷新并重新确认。", "The shared partition's disk or range changed. Refresh and review the selection again."));
        }
    }
}
