using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public sealed record UsbPartition(int Number, string Guid, long Offset, long Size, string Type, bool IsBoot, bool IsSystem, string[] AccessPaths);
public sealed record UsbDisk(int Number, string UniqueId, string Serial, string Model, long Size, int SectorSize, string Bus, string Style,
    bool IsBoot, bool IsSystem, bool IsOffline, bool IsReadOnly, string Health, string[] Operational, UsbPartition[] Partitions);
public sealed record UsbInventory(int Schema, int SourceDiskNumber, UsbDisk[] Disks);
public sealed record UsbChoice(UsbDisk Disk, string Reason)
{
    public bool Eligible => Reason.Length == 0;
    public override string ToString() => $"磁盘 {Disk.Number} · {Disk.Model} · {Disk.Size / 1073741824d:F1} GiB · {Disk.Serial}" + (Eligible ? " · 可核对" : " · " + Reason);
}
public static class UsbMediaPlanning
{
    private static readonly JsonSerializerOptions JsonOptions = new() { RespectRequiredConstructorParameters = true };
    public static UsbInventory Parse(string json)
    {
        var snapshot = JsonSerializer.Deserialize<UsbInventory>(json, JsonOptions) ?? throw new IOException("USB inventory is empty.");
        if (snapshot.Schema != 1 || snapshot.Disks.Length == 0 || snapshot.Disks.Count(d => d.Number == snapshot.SourceDiskNumber) != 1
            || snapshot.Disks.Select(d => d.Number).Distinct().Count() != snapshot.Disks.Length) throw new IOException("USB inventory/source mapping is incomplete or ambiguous.");
        if (snapshot.Disks.Any(d => d.Number < 0 || d.Size <= 0 || d.SectorSize <= 0 || d.Partitions == null || d.Operational == null
            || d.UniqueId == null || d.Serial == null || d.Bus == null || d.Model == null || d.Style == null || d.Health == null)) throw new IOException("USB inventory fields are incomplete.");
        return snapshot;
    }
    public static string Rejection(UsbDisk disk, UsbInventory inventory, long imageBytes)
    {
        if (disk.Bus != "USB") return "设备总线不是 USB";
        if (disk.IsBoot || disk.IsSystem || disk.Partitions.Any(p => p.IsBoot || p.IsSystem)) return "包含 Windows 启动或系统分区";
        if (disk.Number == inventory.SourceDiskNumber) return "保存当前镜像的磁盘";
        if (disk.IsOffline || disk.IsReadOnly) return "设备离线或只读";
        if (disk.SectorSize != 512) return "当前镜像需要 512 字节逻辑扇区";
        if (imageBytes <= 0 || imageBytes % 512 != 0 || disk.Size < imageBytes) return "容量不足或镜像长度无效";
        if (disk.Health != "Healthy" || disk.Operational.Length != 1 || disk.Operational[0] != "Online") return "设备健康或在线状态未知";
        if (disk.Style is not ("RAW" or "MBR" or "GPT")) return "磁盘布局不受支持";
        if (string.IsNullOrWhiteSpace(disk.UniqueId) || string.IsNullOrWhiteSpace(disk.Serial)) return "设备身份或序列号缺失";
        if (inventory.Disks.Count(d => string.Equals(d.UniqueId, disk.UniqueId, StringComparison.OrdinalIgnoreCase)) != 1
            || inventory.Disks.Count(d => string.Equals(d.Serial, disk.Serial, StringComparison.OrdinalIgnoreCase)) != 1) return "设备身份或序列号重复";
        long end = 0;
        foreach (var part in disk.Partitions.OrderBy(p => p.Offset))
        {
            if (part.Offset < end || part.Offset < 0 || part.Size <= 0 || part.Size > disk.Size - part.Offset || part.AccessPaths == null) return "分区范围或卷路径无效";
            end = part.Offset + part.Size;
        }
        return "";
    }
    public static UsbChoice[] Choices(UsbInventory inventory, long imageBytes) => inventory.Disks.Where(d => d.Bus == "USB").Select(d => new UsbChoice(d, Rejection(d, inventory, imageBytes))).ToArray();
    public static UsbDisk Rebind(UsbDisk reviewed, UsbInventory fresh, long imageBytes)
    {
        var matches = fresh.Disks.Where(d => string.Equals(d.UniqueId, reviewed.UniqueId, StringComparison.OrdinalIgnoreCase)
            && string.Equals(d.Serial, reviewed.Serial, StringComparison.OrdinalIgnoreCase)).ToArray();
        if (matches.Length != 1) throw new IOException("Selected USB is missing, replaced or ambiguous.");
        var now = matches[0]; var reason = Rejection(now, fresh, imageBytes); if (reason.Length != 0) throw new IOException(reason);
        if (now.Size != reviewed.Size || now.SectorSize != reviewed.SectorSize || now.Bus != reviewed.Bus || now.Model != reviewed.Model || now.Style != reviewed.Style)
            throw new IOException("USB device metadata changed; review again.");
        string Parts(UsbDisk disk) => JsonSerializer.Serialize(disk.Partitions.OrderBy(p => p.Offset).Select(p => new { p.Guid, p.Offset, p.Size, p.Type, p.IsBoot, p.IsSystem, AccessPaths = p.AccessPaths.Order(StringComparer.OrdinalIgnoreCase) }));
        if (Parts(now) != Parts(reviewed)) throw new IOException("USB partition layout/volume paths changed; review again.");
        return now; // Number is freshly discovered; it is never used as identity.
    }
    public static async Task<UsbInventory> ReadAsync(string source, CancellationToken token)
    {
        var image = MediaSource.Read(source);
        var json = await Backend.PowerShellAsync("read-usb-media.ps1", ["-SourcePath", image.Path], _ => { }, token);
        return Parse(json);
    }
}
