using System.Buffers.Binary;
using System.IO;
using System.Text;

namespace OxpInstaller;

// A bounded, read-only format/layout check. Compressed inputs are checked again
// after ImportAsync extracts the raw image, before any guest or staging work.
internal static class RecoveryImage
{
    private static readonly string[] Roles = ["esp", "efi-A", "rootfs-A", "var-A", "home"];

    internal static void ValidateSelection(string path)
    {
        if (!File.Exists(path)) throw new IOException(PartitionInventory.L("请选择存在的恢复镜像。", "Select an existing recovery image."));
        if (path.EndsWith(".img", StringComparison.OrdinalIgnoreCase)) ValidateRaw(path);
        else if (!path.EndsWith(".img.bz2", StringComparison.OrdinalIgnoreCase)
            && !path.EndsWith(".img.zip", StringComparison.OrdinalIgnoreCase))
            throw new IOException(PartitionInventory.L("请选择 .img、.img.bz2 或 .img.zip 恢复镜像。", "Select an .img, .img.bz2 or .img.zip recovery image."));
    }

    internal static void ValidateRaw(string path)
    {
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length >= 0x10048 && At(file, 0x10040, 8).AsSpan().SequenceEqual("_BHRfS_M"u8))
            throw new IOException(PartitionInventory.L(
                "这是 rootfs.img 类型的单独 Btrfs 系统分区镜像，不能用作恢复镜像。请在“恢复镜像”中选择完整 SteamOS 恢复镜像；此文件应在“3.10 镜像”中导入。",
                "This is a standalone Btrfs system partition image (rootfs.img), not a recovery disk. Select a complete SteamOS recovery image under Recovery image; import this file under 3.10 image."));

        if (file.Length < 34 * 512 || file.Length % 512 != 0) throw Invalid();
        var sectors = (ulong)(file.Length / 512);
        var mbr = At(file, 0, 512);
        var header = At(file, 512, 512);
        var headerSize = U32(header, 12);
        if (mbr[510] != 0x55 || mbr[511] != 0xaa || !header.AsSpan(0, 8).SequenceEqual("EFI PART"u8)
            || U32(header, 8) != 0x10000 || headerSize < 92 || headerSize > 512
            || U64(header, 24) != 1 || U64(header, 32) != sectors - 1
            || new Guid(header.AsSpan(56, 16)) == Guid.Empty) throw Invalid();
        var savedCrc = U32(header, 16);
        header.AsSpan(16, 4).Clear();
        if (Crc(header.AsSpan(0, (int)headerSize)) != savedCrc) throw Invalid();

        var first = U64(header, 40); var last = U64(header, 48);
        var tableLba = U64(header, 72); var count = U32(header, 80); var width = U32(header, 84);
        if (first < 34 || first > last || last >= sectors - 1 || tableLba < 2
            || count == 0 || count > 128 || width != 128) throw Invalid();
        var tableSize = (int)count * 128;
        var tableSectors = (ulong)((tableSize + 511) / 512);
        if (tableLba > first || tableSectors > first - tableLba) throw Invalid();
        var entries = At(file, checked((long)tableLba * 512), tableSize);
        if (Crc(entries) != U32(header, 88)) throw Invalid();
        var names = new List<string>(); var ids = new HashSet<Guid>(); var previousEnd = first - 1;
        for (var i = 0; i < count; i++)
        {
            var entry = entries.AsSpan(i * 128, 128);
            if (new Guid(entry[..16]) == Guid.Empty) continue;
            var start = BinaryPrimitives.ReadUInt64LittleEndian(entry[32..]);
            var end = BinaryPrimitives.ReadUInt64LittleEndian(entry[40..]);
            var id = new Guid(entry.Slice(16, 16));
            if (i != names.Count || id == Guid.Empty || !ids.Add(id) || start <= previousEnd
                || start < first || end < start || end > last) throw Invalid();
            names.Add(Encoding.Unicode.GetString(entry[56..]).TrimEnd('\0'));
            previousEnd = end;
        }
        if (!names.SequenceEqual(Roles)) throw Invalid();
    }

    private static IOException Invalid() => new(PartitionInventory.L(
        "恢复镜像的 GPT 分区表或分区布局无效。请选择包含 esp、efi-A、rootfs-A、var-A、home 分区的完整 SteamOS 恢复镜像；文件可能选错、损坏或未下载完整。",
        "The recovery image has an invalid GPT partition table or layout. Select a complete SteamOS recovery image containing esp, efi-A, rootfs-A, var-A and home. The selected file may be incorrect, damaged or incomplete."));

    private static byte[] At(FileStream file, long offset, int length)
    {
        if (offset < 0 || offset > file.Length || length > file.Length - offset) throw Invalid();
        var bytes = new byte[length]; file.Position = offset; file.ReadExactly(bytes); return bytes;
    }
    private static uint U32(byte[] bytes, int offset) => BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(offset));
    private static ulong U64(byte[] bytes, int offset) => BinaryPrimitives.ReadUInt64LittleEndian(bytes.AsSpan(offset));
    private static uint Crc(ReadOnlySpan<byte> bytes)
    {
        uint crc = uint.MaxValue;
        foreach (var value in bytes)
        {
            crc ^= value;
            for (var bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0 : 0xedb88320u);
        }
        return ~crc;
    }
}
