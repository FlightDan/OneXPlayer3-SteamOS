using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
namespace OxpInstaller;
public sealed record NativeDiskInfo(int Number, long Size, int SectorSize, uint Bus, string Serial, string Vendor, string Product, bool Removable);
public sealed record NativePartition(int Number, long Offset, long Size, Guid Id, uint Style, string Type);
public sealed record NativeLayout(uint Style, Guid DiskId, NativePartition[] Partitions);
internal static class NativeMediaIo
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool DeviceIoControl(SafeFileHandle handle, uint code, byte[]? input, uint inputLength, byte[] output, uint outputLength, out uint returned, IntPtr overlapped);
    public static SafeFileHandle OpenReadOnlyDisk(int number)
    {
        if (number < 0) throw new IOException("Invalid reviewed device number.");
        return Open(@"\\.\PhysicalDrive" + number.ToString(System.Globalization.CultureInfo.InvariantCulture), 0x80000000);
    }
    public static SafeFileHandle OpenVolumeMetadata(string path)
    {
        NativeVolumes.ValidatePath(path); return Open(path[..^1], 0);
    }
    private static SafeFileHandle Open(string path, uint access)
    {
        var handle = CreateFile(path, access, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
        if (handle.IsInvalid) { var code = Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(code, "Open read-only media metadata handle"); }
        return handle;
    }
    public static byte[] Query(SafeFileHandle handle, uint code, int length, int minimum, byte[]? input = null)
    {
        var output = new byte[length];
        if (!DeviceIoControl(handle, code, input, (uint)(input?.Length ?? 0), output, (uint)output.Length, out var returned, IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Read native media metadata");
        if (returned < minimum || returned > output.Length) throw new IOException("Short or oversized native media response.");
        return output[..(int)returned];
    }
}
public static class NativeMediaDevice
{
    public static NativeDiskInfo Read(SafeFileHandle handle)
    {
        var device = NativeMediaIo.Query(handle, 0x2d1080, 12, 12);
        if (BitConverter.ToUInt32(device) != 7 || BitConverter.ToUInt32(device, 4) > int.MaxValue) throw new IOException("Expected a native disk device.");
        var size = BitConverter.ToInt64(NativeMediaIo.Query(handle, 0x7405c, 8, 8));
        var sector = BitConverter.ToUInt32(NativeMediaIo.Query(handle, 0x70000, 24, 24), 20);
        var input = new byte[12]; var header = NativeMediaIo.Query(handle, 0x2d1400, 8, 8, input); var required = BitConverter.ToUInt32(header, 4);
        if (required < 36 || required > 65536) throw new IOException("Invalid native device descriptor size.");
        var descriptor = NativeMediaIo.Query(handle, 0x2d1400, (int)required, 36, input);
        if (BitConverter.ToUInt32(descriptor, 4) > descriptor.Length || size <= 0 || sector == 0 || sector > int.MaxValue) throw new IOException("Invalid native device descriptor/capacity.");
        string Text(int at)
        {
            var offset = BitConverter.ToUInt32(descriptor, at); if (offset == 0) return "";
            if (offset < 36 || offset >= descriptor.Length) throw new IOException("Native descriptor string is out of bounds.");
            var end = Array.IndexOf(descriptor, (byte)0, (int)offset);
            if (end < 0 || descriptor.AsSpan((int)offset, end - (int)offset).ContainsAnyExceptInRange((byte)32, (byte)126)) throw new IOException("Native descriptor text is invalid.");
            return Encoding.ASCII.GetString(descriptor, (int)offset, end - (int)offset).Trim();
        }
        return new((int)BitConverter.ToUInt32(device, 4), size, (int)sector, BitConverter.ToUInt32(descriptor, 28), Text(24), Text(12), Text(16), descriptor[10] != 0);
    }
    public static NativeLayout ReadLayout(SafeFileHandle handle, long capacity)
    {
        return ParseLayout(NativeMediaIo.Query(handle, 0x70050, 1024 * 1024, 48), capacity);
    }
    internal static NativeLayout ParseLayout(byte[] data, long capacity)
    {
        if (data.Length < 48 || capacity <= 0) throw new IOException("Short native layout or invalid capacity.");
        var style = BitConverter.ToUInt32(data); var count = BitConverter.ToUInt32(data, 4);
        if (style > 2 || count > (data.Length - 48) / 144) throw new IOException("Invalid native partition layout response.");
        var parts = new List<NativePartition>(); long end = 0;
        for (var index = 0; index < count; index++)
        {
            var at = 48 + index * 144; var offset = BitConverter.ToInt64(data, at + 8); var size = BitConverter.ToInt64(data, at + 16);
            if (size == 0) continue;
            var entryStyle = BitConverter.ToUInt32(data, at); var number = BitConverter.ToUInt32(data, at + 24);
            if (entryStyle != style || number == 0 || number > int.MaxValue || offset < 0 || size < 0 || size > capacity - offset || offset % 512 != 0 || size % 512 != 0) throw new IOException("Invalid native partition bounds/style.");
            var id = style == 1 ? new Guid(data.AsSpan(at + 48, 16)) : Guid.Empty;
            var type = style == 1 ? new Guid(data.AsSpan(at + 32, 16)).ToString() : data[at + 32].ToString("X2");
            if (style == 1 && (id == Guid.Empty || type == Guid.Empty.ToString())) throw new IOException("Native GPT partition identity is missing.");
            parts.Add(new((int)number, offset, size, id, entryStyle, type));
        }
        var ordered = parts.OrderBy(p => p.Offset).ToArray();
        foreach (var part in ordered) { if (part.Offset < end) throw new IOException("Native partition ranges overlap."); end = part.Offset + part.Size; }
        if (ordered.Select(p => p.Number).Distinct().Count() != ordered.Length
            || style == 1 && ordered.Select(p => p.Id).Distinct().Count() != ordered.Length
            || (style == 2 && ordered.Length != 0)) throw new IOException("Native partition numbering/layout is invalid.");
        var diskId = style == 1 ? new Guid(data.AsSpan(8, 16)) : Guid.Empty;
        if (style == 1 && diskId == Guid.Empty) throw new IOException("Native GPT disk identity is missing.");
        return new(style, diskId, ordered);
    }
    public static bool SameLayout(NativeLayout before, NativeLayout after) => before.Style == after.Style && before.DiskId == after.DiskId && before.Partitions.SequenceEqual(after.Partitions);
    public static void MatchReviewedLayout(UsbDisk reviewed, NativeLayout layout)
    {
        var style = reviewed.Style switch { "MBR" => 0u, "GPT" => 1u, "RAW" => 2u, _ => throw new IOException("Unsupported reviewed partition style.") };
        // Windows reports a new uninitialized disk as RAW in MSFT_Disk but its
        // native GET_DRIVE_LAYOUT_EX returns an empty MBR layout on this host.
        // Only a fresh reviewed RAW disk with no partitions/identity admits this.
        var emptyRaw = style == 2 && reviewed.Partitions.Length == 0 && layout.Partitions.Length == 0 && layout.DiskId == Guid.Empty && layout.Style is 0 or 2;
        if ((!emptyRaw && layout.Style != style) || layout.Partitions.Length != reviewed.Partitions.Length) throw new IOException("Native layout differs from the reviewed disk.");
        foreach (var expected in reviewed.Partitions)
        {
            var matches = layout.Partitions.Where(p => p.Number == expected.Number && p.Offset == expected.Offset && p.Size == expected.Size).ToArray();
            if (matches.Length != 1 || (style == 1 && (!Guid.TryParse(expected.Guid, out var id) || id != matches[0].Id))) throw new IOException("Native partition identity/range differs from review.");
        }
    }
    public static void MatchUsb(UsbDisk reviewed, NativeDiskInfo native)
    {
        if (native.Bus != 7 || reviewed.Bus != "USB" || native.Number != reviewed.Number || native.Size != reviewed.Size || native.SectorSize != 512 || reviewed.SectorSize != 512
            || string.IsNullOrWhiteSpace(native.Serial) || !string.Equals(native.Serial, reviewed.Serial, StringComparison.OrdinalIgnoreCase)) throw new IOException("Native USB handle identity/capacity/sector does not match review.");
    }
    internal static SafeFileHandle OpenReviewedUsbReadOnly(UsbDisk fresh)
    {
        if (fresh.Bus != "USB" || fresh.IsBoot || fresh.IsSystem || fresh.IsOffline || fresh.IsReadOnly) throw new IOException("USB review protection state rejected.");
        var handle = NativeMediaIo.OpenReadOnlyDisk(fresh.Number);
        try { MatchUsb(fresh, Read(handle)); MatchReviewedLayout(fresh, ReadLayout(handle, fresh.Size)); return handle; }
        catch { handle.Dispose(); throw; }
    }
}
