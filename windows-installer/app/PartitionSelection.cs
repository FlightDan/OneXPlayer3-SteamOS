using System.Globalization;
using System.Text.Json;

namespace OxpInstaller;

// A read-only plan. This is deliberately not a physical-disk write capability.
public sealed record PartitionSelection(string Snapshot, bool Example, int Disk, long Start, long Capacity, bool AlignRight = false)
{
    public SpaceChoice Target()
    {
        var gap = PartitionInventory.Read(Snapshot).SelectMany(d => d.Rows).Select(r => r.Space)
            .SingleOrDefault(s => s != null && s.Disk == Disk && s.Start == Start)
            ?? throw new InvalidOperationException(PartitionInventory.L("请重新选择有效的未分配空间。", "Select an eligible unallocated region again."));
        if (Capacity < PartitionInventory.Minimum || Capacity > gap.Size || Capacity % PartitionInventory.MiB != 0)
            throw new InvalidOperationException(PartitionInventory.L("安装容量必须在 64 GiB 与所选空间上限之间，且按 MiB 对齐。", "Capacity must be between 64 GiB and the selected region size, aligned to MiB."));
        var target = gap with { Start = AlignRight ? checked(gap.Start + gap.Size - Capacity) : gap.Start, Size = Capacity };
        DiskPlanning.Layout(target);
        return target;
    }
}

public sealed record PartitionRow(int Disk, long Start, long Size, string Name, string Type, long? Free, string Status, SpaceChoice? Space = null, bool CanDelete = false)
{
    public string CapacityText => PartitionInventory.SizeText(Size);
    public string FreeText => Free.HasValue ? PartitionInventory.SizeText(Free.Value) : "—";
}
public sealed record InventoryDisk(int Number, string Model, long Size, string Bus, string Style, PartitionRow[] Rows)
{
    public string Title => $"{PartitionInventory.L("磁盘", "Disk")} {Number} · {Model} · {PartitionInventory.SizeText(Size)} · {Bus} / {Style}";
    public override string ToString() => Title;
}
public sealed record LayoutSegment(string Name, long Start, long Size, string Action);

public static class PartitionInventory
{
    public const long MiB = 1024L * 1024, GiB = 1024L * MiB, Minimum = 64 * GiB;
    public static string L(string zh, string en) => InstallerI18n.Language == "en-US" ? en : zh;
    public static string SizeText(long bytes) => bytes >= GiB ? $"{bytes / (decimal)GiB:0.##} GiB" : $"{bytes / (decimal)MiB:0.##} MiB";
    public static long ParseCapacity(string value, long maximum)
    {
        if (!decimal.TryParse(value, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var gib)
            || gib < 64 || gib > maximum / (decimal)GiB)
            throw new InvalidOperationException(L($"请输入 64 至 {maximum / (decimal)GiB:0.######} GiB 的容量。", $"Enter a capacity from 64 to {maximum / (decimal)GiB:0.######} GiB."));
        return checked((long)decimal.Floor(gib * 1024) * MiB);
    }
    public static InventoryDisk[] Read(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var result = new List<InventoryDisk>();
        var diskNumbers = new HashSet<int>();
        foreach (var disk in doc.RootElement.EnumerateArray())
        {
            var number = disk.GetProperty("number").GetInt32();
            if (!diskNumbers.Add(number)) throw new InvalidOperationException("Duplicate disk number.");
            var size = disk.GetProperty("size").GetInt64();
            if (size < 2 * MiB) continue;
            string Str(JsonElement e, string key) => e.TryGetProperty(key, out var v) ? v.GetString() ?? "" : "";
            bool Flag(string key) => disk.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.True;
            var model = Str(disk, "model"); var bus = Str(disk, "bus"); var style = Str(disk, "style");
            var reason = Str(disk, "partitionReadError").Length > 0 ? L("分区读取不完整，请刷新磁盘", "Incomplete partition inventory; refresh disks")
                : Flag("isOffline") ? L("磁盘脱机", "Disk offline") : Flag("isReadOnly") ? L("磁盘只读", "Read-only disk")
                : style != "GPT" ? L("需要 GPT 分区表", "GPT required")
                : bus is not ("NVMe" or "SATA" or "USB" or "SD" or "MMC") ? L("当前不支持此接口", "Unsupported bus")
                : !disk.TryGetProperty("sectorSize", out var sector) || sector.GetInt32() != 512 ? L("当前需要 512 字节逻辑扇区", "512-byte logical sectors required") : "";
            List<SpaceChoice> eligible = [];
            if (reason.Length == 0)
            {
                try { eligible = DiskPlanning.FreeSpaces("[" + disk.GetRawText() + "]"); }
                catch (InvalidOperationException) { reason = L("分区标识或布局无效", "Invalid partition identity or layout"); }
            }
            var rows = new List<PartitionRow>(); long cursor = MiB;
            if (Str(disk, "partitionReadError").Length > 0) {
                rows.Add(new(number, 0, size, L("分区布局不可用", "Partition layout unavailable"), "?", null, reason));
                result.Add(new(number, model, size, bus, style, rows.ToArray()));
                continue;
            }
            foreach (var part in disk.GetProperty("partitions").EnumerateArray().OrderBy(p => p.GetProperty("offset").GetInt64()))
            {
                var start = part.GetProperty("offset").GetInt64(); var bytes = part.GetProperty("size").GetInt64();
                if (start < 0 || bytes <= 0 || start > size - bytes || start < cursor && rows.Count > 0)
                    throw new InvalidOperationException(L("磁盘布局重叠或越界，请刷新后重试。", "Overlapping or out-of-bounds layout; refresh and retry."));
                AddGap(cursor, start);
                var letter = Str(part, "letter").Trim('\0'); var label = Str(part, "label");
                var name = $"{L("分区", "Partition")} {part.GetProperty("number").GetInt32()}" + (letter.Length > 0 ? $" · {letter}:" : "") + (label.Length > 0 ? $" · {label}" : "");
                var type = Str(part, "type") switch { "System" => "EFI", "Reserved" => "MSR", "Recovery" => L("恢复分区", "Recovery"), _ => Str(part, "filesystem") };
                if (type.Length == 0) type = L("未知文件系统", "Unknown filesystem");
                if (part.TryGetProperty("isBoot", out var boot) && boot.ValueKind == JsonValueKind.True) type += " · Windows";
                long? free = part.TryGetProperty("free", out var f) && f.ValueKind == JsonValueKind.Number ? f.GetInt64() : null;
                var canDelete = reason.Length == 0 && PartitionDeletion.Allowed(disk, part);
                rows.Add(new(number, start, bytes, name, type, free, canDelete
                    ? L("可删除以释放空间（清空数据）", "Can delete to free space (erases data)")
                    : L("受保护 / 不支持删除", "Protected / deletion unavailable"), CanDelete: canDelete));
                cursor = checked(start + bytes);
            }
            AddGap(cursor, size / MiB * MiB - MiB);
            result.Add(new(number, model, size, bus, style, rows.ToArray()));
            void AddGap(long start, long end)
            {
                start = checked((start + MiB - 1) / MiB * MiB); end = end / MiB * MiB;
                if (end <= start) return;
                var space = eligible.SingleOrDefault(s => s.Start == start && s.Size == end - start);
                var status = space != null ? L("可安装 SteamOS", "Available for SteamOS") : reason.Length > 0 ? reason
                    : end - start < Minimum ? L("不足 64 GiB", "Less than 64 GiB") : L("缺少有效 GPT 标识", "Missing valid GPT identity");
                rows.Add(new(number, start, end - start, L("未分配空间", "Unallocated space"), "—", end - start, status, space));
            }
        }
        return result.ToArray();
    }
    public static LayoutSegment[] Before(InventoryDisk disk) => disk.Rows.Select(r => new LayoutSegment(r.Name, r.Start, r.Size,
        r.Type == "—" ? "free" : "keep")).ToArray();
    public static LayoutSegment[] After(PartitionSelection selection)
    {
        var target = selection.Target(); var disk = Read(selection.Snapshot).Single(d => d.Number == target.Disk);
        var segments = new List<LayoutSegment>();
        foreach (var row in disk.Rows)
        {
            if (row.Start != selection.Start || row.Space == null) { segments.Add(new(row.Name, row.Start, row.Size, row.Type == "—" ? "free" : "keep")); continue; }
            if (target.Start > row.Start) segments.Add(new(L("剩余未分配", "Remaining unallocated"), row.Start, target.Start - row.Start, "free"));
            var layout = JsonSerializer.SerializeToElement(DiskPlanning.Layout(target));
            foreach (var p in layout.EnumerateArray()) segments.Add(new(p.GetProperty("name").GetString()!, p.GetProperty("start").GetInt64(), p.GetProperty("size").GetInt64(), "new"));
            var targetEnd = checked(target.Start + target.Size); var rowEnd = checked(row.Start + row.Size);
            if (rowEnd > targetEnd) segments.Add(new(L("剩余未分配", "Remaining unallocated"), targetEnd, rowEnd - targetEnd, "free"));
        }
        return segments.ToArray();
    }
    public static string ExampleJson => AddExampleDeletionMetadata(JsonSerializer.Serialize(new[] { new {
        number = 0, model = L("示例 NVMe（非实际设备）", "Example NVMe (not a real device)"), size = 512 * GiB, bus = "NVMe", style = "GPT",
        guid = "11111111-1111-1111-1111-111111111111", sectorSize = 512,
        partitions = new[] {
            new { number = 1, offset = MiB, size = 260 * MiB, type = "System", filesystem = "FAT32", letter = "", label = "EFI", isBoot = false, free = 200 * MiB, guid = "22222222-2222-2222-2222-222222222222", gptType = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B" },
            new { number = 2, offset = 261 * MiB, size = 16 * MiB, type = "Reserved", filesystem = "", letter = "", label = "", isBoot = false, free = 0L, guid = "33333333-3333-3333-3333-333333333333", gptType = "E3C9E316-0B5C-4DB8-817D-F92DF00215AE" },
            new { number = 3, offset = 277 * MiB, size = 280 * GiB, type = "Basic", filesystem = "NTFS", letter = "C", label = "Windows", isBoot = true, free = 120 * GiB, guid = "44444444-4444-4444-4444-444444444444", gptType = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7" },
            new { number = 5, offset = 277 * MiB + 280 * GiB, size = 96 * GiB, type = "Basic", filesystem = "NTFS", letter = "D", label = "Data", isBoot = false, free = 40 * GiB, guid = "77777777-7777-7777-7777-777777777777", gptType = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7" },
            new { number = 4, offset = 511 * GiB, size = 512 * MiB, type = "Recovery", filesystem = "NTFS", letter = "", label = "", isBoot = false, free = 0L, guid = "55555555-5555-5555-5555-555555555555", gptType = "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC" }
        }
    }}));
    private static string AddExampleDeletionMetadata(string json)
    {
        var root = System.Text.Json.Nodes.JsonNode.Parse(json)!;
        root[0]!["isOffline"] = false; root[0]!["isReadOnly"] = false;
        foreach (var part in root[0]!["partitions"]!.AsArray())
        {
            part!["isSystem"] = (int)part["number"]! == 1; part["isHidden"] = false;
            part["deletionAllowed"] = (int)part["number"]! == 5;
        }
        return root.ToJsonString();
    }
}
