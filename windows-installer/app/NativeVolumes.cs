using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
namespace OxpInstaller;
public sealed record NativeExtent(int DiskNumber, long Offset, long Size);
public sealed record NativeVolume(string Path, NativeExtent[] Extents);
public static class NativeVolumes
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr FindFirstVolume(StringBuilder name, uint length);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool FindNextVolume(IntPtr search, StringBuilder name, uint length);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool FindVolumeClose(IntPtr search);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetFinalPathNameByHandle(SafeFileHandle file, StringBuilder name, uint length, uint flags);
    public static void ValidatePath(string path)
    {
        if (path.Length != 49 || !path.StartsWith(@"\\?\Volume{", StringComparison.OrdinalIgnoreCase) || !path.EndsWith(@"}\", StringComparison.Ordinal) || !Guid.TryParse(path.Substring(11, 36), out _)) throw new IOException("Expected a native volume GUID path.");
    }
    public static NativeExtent[] ReadExtents(SafeFileHandle handle, string? volumePath = null)
    {
        try { return ParseExtents(NativeMediaIo.Query(handle, 0x560000, 65536, 8)); }
        catch (IOException error) when (volumePath != null)
        { throw new IOException($"Native volume {volumePath}: {error.Message}", error); }
        catch (Win32Exception error) when (volumePath != null)
        { throw new Win32Exception(error.NativeErrorCode, $"Native volume {volumePath}: {error.Message} (Win32 {error.NativeErrorCode})."); }
    }
    internal static NativeExtent[] ParseExtents(byte[] data)
    {
        // VOLUME_DISK_EXTENTS: 8-byte header followed by 24-byte DISK_EXTENT
        // records (DWORD, alignment padding, LARGE_INTEGER, LARGE_INTEGER).
        if (data.Length < 8) throw new IOException($"Short native volume extents response: bytes={data.Length}.");
        var count = BitConverter.ToUInt32(data);
        if (count == 0 || count > (data.Length - 8) / 24) throw new IOException($"Missing or invalid native volume extents: count={count}, bytes={data.Length}.");
        var extents = new List<NativeExtent>();
        for (var i = 0; i < count; i++)
        {
            var at = 8 + i * 24; var number = BitConverter.ToUInt32(data, at); var offset = BitConverter.ToInt64(data, at + 8); var size = BitConverter.ToInt64(data, at + 16);
            if (number > int.MaxValue || offset < 0 || size <= 0 || offset > long.MaxValue - size)
                throw new IOException($"Invalid native volume extent bounds: index={i}, disk={number}, offset={offset}, size={size}, count={count}, bytes={data.Length}.");
            extents.Add(new((int)number, offset, size));
        }
        return extents.ToArray();
    }
    public static NativeVolume FromOpenFile(FileStream source)
    {
        var name = new StringBuilder(4096); var size = GetFinalPathNameByHandle(source.SafeFileHandle, name, 4096, 1);
        if (size == 0 || size >= 4096 || name.Length < 49) throw new Win32Exception(Marshal.GetLastWin32Error(), "Resolve source handle volume");
        var path = name.ToString()[..49]; ValidatePath(path);
        using var handle = NativeMediaIo.OpenVolumeMetadata(path); return new(path, ReadExtents(handle, path));
    }
    public static NativeVolume RequireDifferentSource(FileStream source, int targetNumber)
    {
        var volume = FromOpenFile(source);
        if (volume.Extents.Length != 1 || volume.Extents.Any(e => e.DiskNumber == targetNumber)) throw new IOException("Source image volume is spanned, ambiguous or on the selected target disk.");
        return volume;
    }
    public static NativeVolume[] FindForDisk(int number, long capacity)
    {
        var name = new StringBuilder(1024); var search = FindFirstVolume(name, 1024);
        if (search == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Begin native volume discovery");
        var found = new List<NativeVolume>(); var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            while (true)
            {
                var path = name.ToString(); ValidatePath(path); if (!visited.Add(path)) throw new IOException("Duplicate native volume enumeration.");
                using var handle = NativeMediaIo.OpenVolumeMetadata(path);
                // Optical volumes can return a successful but empty/invalid
                // VOLUME_DISK_EXTENTS response. Identify them before parsing;
                // they cannot overlap a target hard-disk partition.
                uint deviceType = 0;
                try { deviceType = BitConverter.ToUInt32(NativeMediaIo.Query(handle, 0x2d1080, 12, 12)); }
                catch (Exception error) when (error is IOException or Win32Exception) { }
                NativeExtent[] extents = deviceType == 2 ? [] : ReadExtents(handle, path);
                if (extents.Any(e => e.DiskNumber == number))
                {
                    if (extents.Length != 1 || extents[0].Size > capacity - extents[0].Offset) throw new IOException("Target volume is spanned or outside its native disk.");
                    found.Add(new(path, extents));
                }
                if (FindNextVolume(search, name, 1024)) continue;
                var code = Marshal.GetLastWin32Error(); if (code != 18) throw new Win32Exception(code, "Continue native volume discovery"); break;
            }
        }
        finally { FindVolumeClose(search); }
        return found.OrderBy(v => v.Path, StringComparer.OrdinalIgnoreCase).ToArray();
    }
    public static NativeVolume[] RequireComplete(int number, long capacity, string[] expected)
    {
        var found = FindForDisk(number, capacity);
        if (expected.Distinct(StringComparer.OrdinalIgnoreCase).Count() != expected.Length || !found.Select(v => v.Path).ToHashSet(StringComparer.OrdinalIgnoreCase).SetEquals(expected)) throw new IOException("Target volume list is incomplete or changed; review again.");
        return found;
    }
}
