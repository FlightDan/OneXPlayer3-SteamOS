using System.IO;
using System.Buffers.Binary;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

internal static class RawImageStaging
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(SafeFileHandle file, uint code, IntPtr input, uint inputSize,
        IntPtr output, uint outputSize, out uint returned, IntPtr overlapped);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(SafeFileHandle file, uint code, byte[] input, uint inputSize,
        byte[] output, uint outputSize, out uint returned, IntPtr overlapped);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetVolumePathName(string path, StringBuilder volume, uint length);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetDiskFreeSpace(string root, out uint sectorsPerCluster, out uint bytesPerSector,
        out uint freeClusters, out uint totalClusters);

    private static ulong? AllocationUnit(string directory)
    {
        var volume = new StringBuilder(32768);
        if (!GetVolumePathName(directory, volume, (uint)volume.Capacity)
            || !GetDiskFreeSpace(volume.ToString(), out var sectors, out var bytes, out _, out _)
            || sectors == 0 || bytes == 0) return null;
        // Sparse NTFS ranges may consume a 64-KiB unit even on 4-KiB clusters.
        return Math.Max(65536ul, (ulong)sectors * bytes);
    }

    // QEMU's Windows raw map can report holes as nonzero data. Query logical
    // allocated ranges instead of using compressed byte counts, which could
    // underestimate nonzero data on a compressed NTFS volume.
    internal static ulong? SparseDataUpperBound(FileStream source, CancellationToken token, ulong allocationUnit = 65536)
    {
        if (allocationUnit == 0 || allocationUnit > long.MaxValue) throw new ArgumentOutOfRangeException(nameof(allocationUnit));
        if (!File.GetAttributes(source.Name).HasFlag(FileAttributes.SparseFile)) return null;
        var capacity = source.Length;
        var input = new byte[16]; var output = new byte[4096];
        long cursor = 0; ulong allocated = 0, allocatedEnd = 0;
        while (cursor < capacity)
        {
            token.ThrowIfCancellationRequested();
            BinaryPrimitives.WriteInt64LittleEndian(input, cursor);
            BinaryPrimitives.WriteInt64LittleEndian(input.AsSpan(8), capacity - cursor);
            var complete = DeviceIoControl(source.SafeFileHandle, 0x940cf, input, (uint)input.Length,
                output, (uint)output.Length, out var returned, IntPtr.Zero);
            // Unsupported filesystem/driver: retain the conservative QEMU map.
            if (!complete && Marshal.GetLastWin32Error() != 234) return null;
            if (returned > output.Length || returned % 16 != 0 || !complete && returned == 0)
                throw new IOException("Invalid sparse allocation query result.");
            for (var i = 0; i < returned; i += 16)
            {
                var start = BinaryPrimitives.ReadInt64LittleEndian(output.AsSpan(i));
                var length = BinaryPrimitives.ReadInt64LittleEndian(output.AsSpan(i + 8));
                if (start < cursor || start >= capacity || length <= 0 || length > long.MaxValue - start)
                    throw new IOException("Invalid sparse allocation range.");
                var end = Math.Min(capacity, start + length);
                var roundedStart = (ulong)start / allocationUnit * allocationUnit;
                var roundedEnd = checked(((ulong)end + allocationUnit - 1) / allocationUnit * allocationUnit);
                allocated = checked(allocated + roundedEnd - Math.Max(roundedStart, allocatedEnd));
                allocatedEnd = roundedEnd;
                cursor = end;
            }
            if (complete) return allocated;
        }
        return allocated;
    }

    internal static async Task ConvertAsync(string source, string destination, Action<string> log, CancellationToken token)
    {
        MediaSource.Ordinary(destination, InstallationController.Work, false);
        var qemu = Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe");
        // Lock ordinary inputs before inspecting their format; a same-length
        // replacement must not invalidate the raw-file classification.
        using var ordinary = File.Exists(source) ? new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read) : null;
        using var info = JsonDocument.Parse(await Backend.ProcessAsync(qemu, ["info", "--output=json", source], _ => { }, token));
        var capacity = info.RootElement.GetProperty("virtual-size").GetInt64();
        // Keep an ordinary raw input immutable until conversion completes.
        // qcow2 graph inputs continue to use their format-aware QEMU extent map.
        var raw = info.RootElement.GetProperty("format").GetString() == "raw" ? ordinary : null;
        if (raw != null && raw.Length != capacity) throw new IOException("Source image size changed before staging.");
        using var map = JsonDocument.Parse(await Backend.ProcessAsync(qemu, ["map", "--output=json", source], _ => { }, token));
        ulong allocated = 0;
        foreach (var extent in map.RootElement.EnumerateArray())
            if (!extent.TryGetProperty("zero", out var zero) || !zero.GetBoolean())
                allocated = checked(allocated + extent.GetProperty("length").GetUInt64());
        var allocationUnit = AllocationUnit(Path.GetDirectoryName(destination)!);
        var sparseAllocated = raw == null || !allocationUnit.HasValue ? null : SparseDataUpperBound(raw, token, allocationUnit.Value);
        if (sparseAllocated.HasValue) allocated = Math.Min(allocated, sparseAllocated.Value);
        const ulong reserve = 8ul * 1024 * 1024 * 1024;
        bool sparse;
        using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            sparse = DeviceIoControl(output.SafeFileHandle, 0x900c4, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
            MediaSpace.RequireAvailable(Path.GetDirectoryName(destination)!, checked((sparse ? allocated : (ulong)capacity) + reserve));
            output.SetLength(capacity);
        }
        log($"Image staging: logical {capacity / 1073741824d:F1} GiB; data upper bound {allocated / 1073741824d:F1} GiB; sparse={sparse}; allocation source={(sparseAllocated.HasValue ? "Windows sparse ranges" : "QEMU map")}.");
        // Keep the explicitly sparse file. -n prevents qemu from recreating it.
        await Backend.ProcessAsync(qemu, ["convert", "-n", "--target-is-zero", "-S", "4k", "-O", "raw", source, destination], log, token);
    }
}
