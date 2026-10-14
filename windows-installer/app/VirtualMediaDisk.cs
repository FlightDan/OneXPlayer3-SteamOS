using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

// All physical-device paths originate from the handle for this owned
// virtual disk. No caller-supplied disk number or physical path is accepted.
public sealed class VirtualMediaDisk : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] private struct StorageType { public uint DeviceId; public Guid Vendor; }
    [StructLayout(LayoutKind.Explicit, Size = 56)] private struct CreateParameters
    {
        [FieldOffset(0)] public uint Version;
        [FieldOffset(8)] public Guid UniqueId;
        [FieldOffset(24)] public ulong MaximumSize;
        [FieldOffset(32)] public uint BlockSize;
        [FieldOffset(36)] public uint SectorSize;
        [FieldOffset(40)] public IntPtr ParentPath;
        [FieldOffset(48)] public IntPtr SourcePath;
    }
    [StructLayout(LayoutKind.Sequential)] private struct AttachParameters { public uint Version; public uint Reserved; }
    [DllImport("virtdisk.dll", CharSet = CharSet.Unicode)] private static extern uint CreateVirtualDisk(ref StorageType type, string path, uint access, IntPtr security, uint flags, uint provider, ref CreateParameters parameters, IntPtr overlapped, out SafeFileHandle handle);
    [DllImport("virtdisk.dll")] private static extern uint AttachVirtualDisk(SafeFileHandle handle, IntPtr security, uint flags, uint provider, ref AttachParameters parameters, IntPtr overlapped);
    [DllImport("virtdisk.dll", CharSet = CharSet.Unicode)] private static extern uint GetVirtualDiskPhysicalPath(SafeFileHandle handle, ref uint bytes, StringBuilder path);
    [DllImport("virtdisk.dll")] private static extern uint DetachVirtualDisk(SafeFileHandle handle, uint flags, uint provider);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);

    [StructLayout(LayoutKind.Sequential)] private struct OpenParameters { public uint Version, RWDepth; }
    [StructLayout(LayoutKind.Explicit, Size = 52)] private struct FileInformation
    {
        [FieldOffset(28)] public uint Volume;
        [FieldOffset(40)] public uint Links;
        [FieldOffset(44)] public uint IndexHigh;
        [FieldOffset(48)] public uint IndexLow;
    }
    [DllImport("virtdisk.dll", CharSet = CharSet.Unicode)] private static extern uint OpenVirtualDisk(ref StorageType type, string path, uint access, uint flags, ref OpenParameters parameters, out SafeFileHandle handle);
    [DllImport("virtdisk.dll")] private static extern uint GetVirtualDiskInformation(SafeFileHandle handle, ref uint size, byte[] information, out uint used);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInformation information);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetFinalPathNameByHandle(SafeFileHandle file, StringBuilder path, uint size, uint flags);
    private sealed record Ownership(int Schema, string Path, Guid Id, long Size, uint Volume, ulong FileId);
    private FileStream? ownershipLease;
    private SafeFileHandle? fileGuard;
    private SafeFileHandle? disk;
    private bool attached;
    public string PathOnHost { get; }
    public Guid Id { get; } = Guid.NewGuid();
    public long Size { get; }
    public string PhysicalPath { get; private set; } = "";
    public VirtualMediaDisk(string path, long size) : this(path, size, null) { }
    public static VirtualMediaDisk ReopenOwned(string path, long size, Guid id)
    {
        if (id == Guid.Empty) throw new IOException("Missing owned VHD identifier.");
        return new(path, size, id);
    }
    private byte[] Information(uint version)
    {
        var bytes = new byte[32]; BitConverter.GetBytes(version).CopyTo(bytes, 0); uint size = (uint)bytes.Length;
        Check(GetVirtualDiskInformation(disk!, ref size, bytes, out _), "GetVirtualDiskInformation");
        return bytes;
    }
    private VirtualMediaDisk(string path, long size, Guid? resumeId)
    {
        if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
            throw new InvalidOperationException("Windows virtual media validation requires an administrator helper.");
        PathOnHost = Path.GetFullPath(path); Size = size; Id = resumeId ?? Guid.NewGuid();
        var work = InstallerWorkspace.DirectoryPath;
        MediaSource.Ordinary(PathOnHost, work, resumeId.HasValue);
        if (!PathOnHost.EndsWith(".vhd", StringComparison.OrdinalIgnoreCase)
            || size < 16 * 1024 * 1024 || size % 512 != 0 || (!resumeId.HasValue && File.Exists(PathOnHost)))
            throw new IOException("Only a new or explicitly owned work-directory VHD is permitted.");
        Directory.CreateDirectory(Path.GetDirectoryName(PathOnHost)!);
        var receiptPath = PathOnHost + ".owner.json";
        var leasePath = PathOnHost + ".owner.lock";
        MediaSource.Ordinary(receiptPath, work, resumeId.HasValue);
        MediaSource.Ordinary(leasePath, work, false);
        try
        {
            ownershipLease = new(leasePath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.DeleteOnClose);
            Ownership? receipt = null;
            if (resumeId.HasValue)
            {
                using var file = new FileStream(receiptPath, FileMode.Open, FileAccess.Read, FileShare.Read);
                if (file.Length > 16 * 1024) throw new IOException("Oversized ownership record.");
                receipt = JsonSerializer.Deserialize<Ownership>(file) ?? throw new IOException("Missing ownership record.");
                if (receipt.Schema != 1 || receipt.Id != Id || receipt.Size != Size || receipt.Path != PathOnHost)
                    throw new IOException("Owned VHD receipt differs from recovery request.");
            }
            else if (File.Exists(receiptPath)) throw new IOException("Existing ownership receipt cannot be replaced.");
            var type = new StorageType { DeviceId = 2, Vendor = new Guid("EC984AEC-A0F9-47e9-901F-71415A66345B") };
            if (resumeId.HasValue)
            {
                // Hold the ordinary file against replacement before opening the virtual disk.
                fileGuard = OpenFileGuard();
                var actual = FileIdentity();
                if (receipt!.Volume != actual.Volume || receipt.FileId != actual.FileId)
                    throw new IOException("Owned VHD file identity changed.");
                var parameters = new OpenParameters { Version = 1, RWDepth = 1 };
                Check(OpenVirtualDisk(ref type, PathOnHost, 0x003f0000, 0, ref parameters, out var opened), "OpenVirtualDisk");
                disk = opened;
            }
            else
            {
                var parameters = new CreateParameters { Version = 1, UniqueId = Id, MaximumSize = (ulong)size, SectorSize = 512 };
                Check(CreateVirtualDisk(ref type, PathOnHost, 0x003f0000, IntPtr.Zero, 0, 0, ref parameters, IntPtr.Zero, out var created), "CreateVirtualDisk");
                disk = created; fileGuard = OpenFileGuard();
            }
            var nativeSize = Information(1);
            if (new Guid(Information(2).AsSpan(8, 16)) != Id || BitConverter.ToInt64(nativeSize, 8) != Size
                || BitConverter.ToUInt32(nativeSize, 28) != 512 || BitConverter.ToUInt32(Information(7), 8) != 3)
                throw new IOException("Owned VHD native identity, capacity, sector size or provider subtype differs.");
            if (BitConverter.ToUInt32(Information(13), 8) != 0) throw new IOException("Owned VHD is already attached elsewhere.");
            if (!resumeId.HasValue)
            {
                using var record = new FileStream(receiptPath, FileMode.CreateNew, FileAccess.Write, FileShare.None);
                JsonSerializer.Serialize(record, FileIdentity()); record.Flush(true);
            }
            var attach = new AttachParameters { Version = 1 };
            Check(AttachVirtualDisk(disk, IntPtr.Zero, 2, 0, ref attach, IntPtr.Zero), "AttachVirtualDisk"); attached = true;
            var buffer = new StringBuilder(256); uint bytes = 512;
            Check(GetVirtualDiskPhysicalPath(disk, ref bytes, buffer), "GetVirtualDiskPhysicalPath");
            PhysicalPath = buffer.ToString();
            if (!PhysicalPath.StartsWith(@"\\.\PhysicalDrive", StringComparison.Ordinal) || !uint.TryParse(PhysicalPath.AsSpan(17), out _)) throw new IOException("Unexpected virtual disk path.");
        }
        catch { Dispose(); throw; }
    }
    private SafeFileHandle OpenFileGuard()
    {
        var handle = CreateFile(PathOnHost, 0, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
        if (handle.IsInvalid) { var error = Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(error, "Guard owned VHD file"); }
        try
        {
            var name = new StringBuilder(4096); var count = GetFinalPathNameByHandle(handle, name, 4096, 0);
            var final = name.ToString(); if (final.StartsWith(@"\\?\")) final = final[4..];
            if (count == 0 || count >= 4096 || !string.Equals(final, PathOnHost, StringComparison.OrdinalIgnoreCase))
                throw new IOException("Owned VHD final path differs.");
            return handle;
        }
        catch { handle.Dispose(); throw; }
    }
    private Ownership FileIdentity()
    {
        if (!GetFileInformationByHandle(fileGuard!, out var info)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Read owned VHD file identity");
        if (info.Links != 1) throw new IOException("Hard-linked VHD is not accepted.");
        return new(1, PathOnHost, Id, Size, info.Volume, ((ulong)info.IndexHigh << 32) | info.IndexLow);
    }
    private static void Check(uint result, string action) { if (result != 0) throw new Win32Exception((int)result, action); }
    public int BoundDiskNumber()
    {
        if (!attached || disk == null) throw new InvalidOperationException("Owned VHD is not attached.");
        var path = new StringBuilder(256); uint bytes = 512;
        Check(GetVirtualDiskPhysicalPath(disk, ref bytes, path), "RebindVirtualDiskPhysicalPath");
        if (path.ToString() != PhysicalPath) throw new IOException("Owned virtual disk binding changed.");
        return int.Parse(PhysicalPath[(PhysicalPath.LastIndexOf("PhysicalDrive", StringComparison.Ordinal) + 13)..], System.Globalization.CultureInfo.InvariantCulture);
    }
    public FileStream OpenDevice()
    {
        if (!attached || disk == null) throw new InvalidOperationException("VHD is not attached.");
        var path = new StringBuilder(256); uint bytes = 512;
        Check(GetVirtualDiskPhysicalPath(disk, ref bytes, path), "RebindVirtualDiskPhysicalPath");
        if (path.ToString() != PhysicalPath) throw new IOException("Virtual disk binding changed.");
        var handle = CreateFile(PhysicalPath, 0xC0000000, 3, IntPtr.Zero, 3, 0x80000000, IntPtr.Zero);
        if (handle.IsInvalid) { handle.Dispose(); throw new Win32Exception(Marshal.GetLastWin32Error(), "Open newly created VHD device"); }
        try
        {
            var native = NativeMediaDevice.Read(handle);
            if (native.Number != BoundDiskNumber() || native.Size != Size || native.SectorSize != 512 || native.Bus != 15)
                throw new IOException("Owned VHD handle number/capacity/sector/bus mismatch.");
            return new FileStream(handle, FileAccess.ReadWrite, 1024 * 1024, false);
        }
        catch { handle.Dispose(); throw; }
    }
    public void Dispose()
    {
        var current = disk; disk = null;
        try { if (attached && current != null) { attached = false; Check(DetachVirtualDisk(current, 0, 0), "DetachVirtualDisk"); } }
        finally
        {
            current?.Dispose(); fileGuard?.Dispose(); fileGuard = null;
            ownershipLease?.Dispose(); ownershipLease = null;
        }
    }
}
