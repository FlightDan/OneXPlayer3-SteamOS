using System.Text.Json;

namespace OxpInstaller;
public sealed record PartitionIdentity(int Number, string Guid, long Offset, long Size, string GptType);
public sealed record DiskIdentity(string DiskGuid, int SectorSize, PartitionIdentity[] Partitions);
public sealed record SpaceChoice(int Disk, string Model, long DiskSize, long Start, long Size, DiskIdentity? Identity = null)
{
    public override string ToString() => $"磁盘 {Disk} · {Model} · 未分配 {Size / 1073741824d:F1} GiB · 起点 {Start}";
}
public static class DiskPlanning
{
    private const long MiB = 1024 * 1024;
    public static string Describe(string json)
    {
        using var document = JsonDocument.Parse(json); var text = new System.Text.StringBuilder();
        foreach (var disk in document.RootElement.EnumerateArray())
        {
            text.AppendLine($"磁盘 {disk.GetProperty("number")} · {disk.GetProperty("model").GetString()} · {disk.GetProperty("size").GetInt64() / 1073741824d:F1} GiB · {disk.GetProperty("bus").GetString()}");
            foreach (var part in disk.GetProperty("partitions").EnumerateArray())
            {
                var role = part.GetProperty("type").GetString() switch { "System" => "EFI 引导", "Reserved" => "保留分区", "Recovery" => "恢复分区", _ => part.GetProperty("filesystem").GetString() };
                var letter = (part.GetProperty("letter").GetString() ?? "").Trim('\0');
                text.AppendLine($"  分区 {part.GetProperty("number")} · {(letter.Length == 0 ? "" : letter + ": · ")}{role} · {part.GetProperty("size").GetInt64() / 1073741824d:F2} GiB{(part.GetProperty("isBoot").GetBoolean() ? " · Windows 系统" : "")}");
            }
        }
        return text.Length == 0 ? "没有读取到磁盘布局。" : text.ToString();
    }
    public static List<SpaceChoice> FreeSpaces(string json)
    {
        using var document = JsonDocument.Parse(json);
        var result = new List<SpaceChoice>();
        foreach (var disk in document.RootElement.EnumerateArray())
        {
            if (disk.TryGetProperty("partitionReadError", out var error) && !string.IsNullOrEmpty(error.GetString())) continue;
            if (disk.TryGetProperty("isOffline", out var offline) && offline.ValueKind == JsonValueKind.True
                || disk.TryGetProperty("isReadOnly", out var readOnly) && readOnly.ValueKind == JsonValueKind.True) continue;
            if (disk.GetProperty("style").GetString() != "GPT" || disk.GetProperty("bus").GetString() is not ("NVMe" or "SATA" or "USB" or "SD" or "MMC")) continue;
            if (!disk.TryGetProperty("guid", out var rawGuid) || !Guid.TryParse(rawGuid.GetString(), out var diskGuid) || diskGuid == Guid.Empty
                || !disk.TryGetProperty("sectorSize", out var sectorSize) || sectorSize.GetInt32() != 512) continue;
            var size = disk.GetProperty("size").GetInt64();
            var partitions = disk.GetProperty("partitions").EnumerateArray().OrderBy(p => p.GetProperty("offset").GetInt64()).ToArray();
            var identities = new List<PartitionIdentity>();
            foreach (var partition in partitions)
            {
                if (!partition.TryGetProperty("guid", out var rawPartGuid) || !Guid.TryParse(rawPartGuid.GetString(), out var partGuid) || partGuid == Guid.Empty
                    || !partition.TryGetProperty("gptType", out var rawType) || !Guid.TryParse(rawType.GetString(), out var type) || type == Guid.Empty)
                    throw new InvalidOperationException("缺少可用于安装交接的 GPT 分区标识。");
                identities.Add(new(partition.GetProperty("number").GetInt32(), partGuid.ToString("D"), partition.GetProperty("offset").GetInt64(), partition.GetProperty("size").GetInt64(), type.ToString("D")));
            }
            if (identities.Select(p => p.Guid).Distinct().Count() != identities.Count || identities.Select(p => p.Number).Distinct().Count() != identities.Count)
                throw new InvalidOperationException("GPT 分区标识或编号重复。");
            var identity = new DiskIdentity(diskGuid.ToString("D"), 512, identities.ToArray());
            var cursor = MiB; var last = size / MiB * MiB - MiB; long previousEnd = 0;
            foreach (var partition in partitions)
            {
                var start = partition.GetProperty("offset").GetInt64(); var bytes = partition.GetProperty("size").GetInt64();
                if (start < previousEnd || bytes <= 0 || checked(start + bytes) > size) throw new InvalidOperationException("磁盘分区元数据越界或重叠。");
                AddGap(cursor, start); cursor = Math.Max(cursor, checked(start + bytes));
                previousEnd = checked(start + bytes);
            }
            AddGap(cursor, last);
            void AddGap(long start, long end)
            {
                start = checked((start + MiB - 1) / MiB * MiB); end = end / MiB * MiB;
                if (end - start >= 64L * 1024 * MiB) result.Add(new(disk.GetProperty("number").GetInt32(), disk.GetProperty("model").GetString() ?? "", size, start, end - start, identity));
            }
        }
        return result;
    }
    public static object Preview(SpaceChoice? target, string[]? resources = null, string[]? components = null) => new
    {
        schema = 1, handoff_schema = 1, stage = "preview_only", allow_disk_write = false, device = "ONEXPLAYER 3",
        source = new { version = "3.8.14", build = "20260707.10" }, components = ValidateComponents(components), plugins = Array.Empty<string>(), target,
        resources = resources ?? Array.Empty<string>(),
        layout = target == null ? null : Layout(target)
    };
    private static string[] ValidateComponents(string[]? choices)
    {
        if (choices is { Length: > 0 }) throw new InvalidOperationException("当前 3.8.14 镜像没有已验收的首次启动组件；HDR 需要匹配的 3.10 系统。");
        return Array.Empty<string>();
    }
    public static object[] Layout(SpaceChoice target)
    {
        if (target.Size < 64L * 1024 * MiB || target.Start < MiB || target.Start % MiB != 0 || checked(target.Start + target.Size) > target.DiskSize - MiB)
            throw new InvalidOperationException("目标未分配空间不满足预览要求。");
        var cursor = target.Start;
        var parts = new List<object>();
        foreach (var (name, size, filesystem) in new[] { ("esp", 256L * MiB, "vfat"), ("efi-A", 64L * MiB, "vfat"), ("efi-B", 64L * MiB, "vfat"), ("rootfs-A", 11264L * MiB, "btrfs"), ("rootfs-B", 11264L * MiB, "btrfs"), ("var-A", 1024L * MiB, "ext4"), ("var-B", 1024L * MiB, "ext4") })
        {
            parts.Add(new { name, start = cursor, size, filesystem }); cursor = checked(cursor + size);
        }
        parts.Add(new { name = "home", start = cursor, size = target.Start + target.Size - cursor, filesystem = "ext4" });
        return parts.ToArray();
    }
}
