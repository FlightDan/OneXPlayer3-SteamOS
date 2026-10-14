using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace OxpInstaller;
public sealed class MediaVolumeLocks : IDisposable
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool DeviceIoControl(SafeFileHandle handle, uint code, IntPtr input, uint inputLength, byte[]? output, uint outputLength, out uint returned, IntPtr overlapped);
    private readonly List<SafeFileHandle> handles = [];
    public int LockedCount => handles.Count;
    private MediaVolumeLocks() { }
    public static MediaVolumeLocks AcquireForOwnedVhd(VirtualMediaDisk disk, string[] paths)
    {
        var number = disk.BoundDiskNumber();
        if (paths.Length == 0 || paths.Distinct(StringComparer.OrdinalIgnoreCase).Count() != paths.Length) throw new IOException("Missing or duplicate owned volume paths.");
        NativeVolumes.RequireComplete(number, disk.Size, paths);
        NativeLayout before;
        using (var raw = disk.OpenDevice()) before = NativeMediaDevice.ReadLayout(raw.SafeFileHandle, disk.Size);
        var scope = new MediaVolumeLocks();
        try
        {
            foreach (var path in paths)
            {
                if (!path.StartsWith(@"\\?\Volume{", StringComparison.OrdinalIgnoreCase) || !path.EndsWith(@"}\", StringComparison.Ordinal) || path.Length != 49
                    || !Guid.TryParse(path.Substring(11, 36), out _)) throw new IOException("Expected a volume GUID path.");
                var handle = CreateFile(path[..^1], 0xC0000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
                if (handle.IsInvalid) { handle.Dispose(); throw new Win32Exception(Marshal.GetLastWin32Error(), "Open owned VHD volume"); }
                try
                {
                    var extents = new byte[64 * 1024];
                    if (!DeviceIoControl(handle, 0x560000, IntPtr.Zero, 0, extents, (uint)extents.Length, out var returned, IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Read volume disk extents");
                    if (returned < 32 || BitConverter.ToUInt32(extents) != 1 || BitConverter.ToUInt32(extents, 8) != number
                        || BitConverter.ToInt64(extents, 16) < 0 || BitConverter.ToInt64(extents, 24) <= 0
                        || BitConverter.ToInt64(extents, 24) > disk.Size - BitConverter.ToInt64(extents, 16)) throw new IOException("Volume does not belong solely to the owned VHD.");
                    Control(handle, 0x90018, "Lock owned VHD volume");
                    scope.handles.Add(handle); handle = null!;
                }
                finally { handle?.Dispose(); }
            }
            if (disk.BoundDiskNumber() != number) throw new IOException("Owned VHD disk number changed after volume locks.");
            using (var raw = disk.OpenDevice())
                if (!NativeMediaDevice.SameLayout(before, NativeMediaDevice.ReadLayout(raw.SafeFileHandle, disk.Size))) throw new IOException("Owned VHD partition layout changed while acquiring locks.");
            // Dismount only after every volume lock has succeeded. Lock failure
            // closes all acquired handles, releasing locks without forcing a dismount.
            foreach (var handle in scope.handles) Control(handle, 0x90020, "Dismount locked owned VHD volume");
            return scope;
        }
        catch { scope.Dispose(); throw; }
    }
    private static void Control(SafeFileHandle handle, uint code, string action)
    {
        if (!DeviceIoControl(handle, code, IntPtr.Zero, 0, null, 0, out _, IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error(), action);
    }
    public void Dispose()
    {
        foreach (var handle in handles.AsEnumerable().Reverse())
        {
            try { DeviceIoControl(handle, 0x9001c, IntPtr.Zero, 0, null, 0, out _, IntPtr.Zero); }
            finally { handle.Dispose(); }
        }
        handles.Clear();
    }
}
