using System.Buffers.Binary;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

public enum InstallationTargetKind { InternalShared, ExternalDisk }
public sealed record PreparedPartition(int Number, string Name, Guid Type, Guid Id, long Offset, long Size, ulong Attributes)
{
    public NativePartition Native => new(Number, Offset, Size, Id, 1, Type.ToString());
}
public sealed record PreparedDisk(Guid Id, long Size, PreparedPartition[] Partitions)
{
    public static readonly string[] Roles = ["esp", "efi-A", "efi-B", "rootfs-A", "rootfs-B", "var-A", "var-B", "home"];
    public PreparedPartition[] System => Partitions.Where(p => Roles.Contains(p.Name)).ToArray();
    public PreparedPartition[] Protected => Partitions.Where(p => !Roles.Contains(p.Name)).ToArray();
    public PreparedPartition[] For(InstallationTargetKind kind) => kind switch
    {
        InstallationTargetKind.InternalShared when Protected.Length > 0 => Partitions,
        InstallationTargetKind.ExternalDisk => System.Select((p, i) => p with { Number = i + 1 }).ToArray(),
        _ => throw new IOException("Unknown target kind or missing protected shared-disk partitions.")
    };
}

// An immutable ordinary staging file, never an attached or caller-selected disk.
// GPT identifiers, bounded entries and primary/backup bytes are read directly;
// no extra content hash or fingerprint is introduced.
public sealed class PreparedDiskImage : IDisposable
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle file, StringBuilder path, uint length, uint flags);
    public FileStream Stream { get; }
    public MediaSource Identity { get; }
    public PreparedDisk Layout { get; }
    public PreparedDiskImage(string path)
    {
        path = Path.GetFullPath(path);
        MediaSource.Ordinary(path, InstallerWorkspace.DirectoryPath);
        if (Path.GetExtension(path) != ".img") throw new IOException("A workspace prepared raw image is required.");
        Stream = new(path, FileMode.Open, FileAccess.Read, FileShare.Read, 4 * 1024 * 1024);
        try
        {
            var name = new StringBuilder(4096); var length = GetFinalPathNameByHandle(Stream.SafeFileHandle, name, 4096, 0);
            var final = name.ToString(); if (final.StartsWith(@"\\?\")) final = final[4..];
            if (length == 0 || length >= 4096 || !string.Equals(final, path, StringComparison.OrdinalIgnoreCase))
                throw new IOException("Prepared source handle path differs.");
            Identity = MediaSource.FromHandle(path, Stream); Layout = Read(Stream);
        }
        catch { Stream.Dispose(); throw; }
    }
    public void Recheck()
    {
        if (MediaSource.FromHandle(Identity.Path, Stream) != Identity) throw new IOException("Prepared source changed.");
    }
    private static byte[] At(FileStream stream, long offset, int length)
    {
        if (offset < 0 || length < 0 || length > stream.Length - offset) throw new IOException("GPT read exceeds image.");
        var bytes = new byte[length]; stream.Position = offset; stream.ReadExactly(bytes); return bytes;
    }
    private static PreparedDisk Read(FileStream file)
    {
        var header = At(file, 512, 512); var size = file.Length;
        if (!header.AsSpan(0, 8).SequenceEqual("EFI PART"u8)
            || BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(12)) != 92
            || BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(24)) != 1
            || BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(32)) != (ulong)(size / 512 - 1))
            throw new IOException("Prepared primary GPT header is not supported.");
        var first = BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(40));
        var last = BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(48));
        var id = new Guid(header.AsSpan(56, 16));
        var entryLba = BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(72));
        var count = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(80));
        var width = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(84));
        if (id == Guid.Empty || entryLba != 2 || count != 128 || width != 128 || first < 34
            || first >= last || last >= (ulong)(size / 512 - 33)) throw new IOException("Invalid prepared GPT capacity or entries.");
        var entries = At(file, 1024, 128 * 128);
        var backup = At(file, size - 512, 512);
        if (!backup.AsSpan(0, 8).SequenceEqual("EFI PART"u8)
            || BinaryPrimitives.ReadUInt32LittleEndian(backup.AsSpan(12)) != 92
            || BinaryPrimitives.ReadUInt64LittleEndian(backup.AsSpan(24)) != (ulong)(size / 512 - 1)
            || BinaryPrimitives.ReadUInt64LittleEndian(backup.AsSpan(32)) != 1
            || !backup.AsSpan(40, 32).SequenceEqual(header.AsSpan(40, 32))
            || !backup.AsSpan(80, 8).SequenceEqual(header.AsSpan(80, 8))
            || BinaryPrimitives.ReadUInt64LittleEndian(backup.AsSpan(72)) != (ulong)(size / 512 - 33)
            || !At(file, size - 33 * 512, entries.Length).AsSpan().SequenceEqual(entries))
            throw new IOException("Prepared backup GPT does not agree.");
        var partitions = new List<PreparedPartition>(); long end = 0; bool emptySeen = false;
        for (var i = 0; i < count; i++)
        {
            var entry = entries.AsSpan(i * 128, 128); var type = new Guid(entry[..16]);
            if (type == Guid.Empty) { emptySeen = true; continue; }
            if (emptySeen) throw new IOException("Holes in prepared GPT numbering are not supported.");
            var partId = new Guid(entry.Slice(16, 16));
            var start = BinaryPrimitives.ReadUInt64LittleEndian(entry[32..]);
            var finish = BinaryPrimitives.ReadUInt64LittleEndian(entry[40..]);
            if (partId == Guid.Empty || start < first || finish < start || finish > last
                || finish >= (ulong)(long.MaxValue / 512)) throw new IOException("Invalid prepared partition bounds or identifier.");
            var offset = checked((long)start * 512); var bytes = checked((long)(finish - start + 1) * 512);
            if (offset < end) throw new IOException("Prepared partition ranges overlap.");
            var name = Encoding.Unicode.GetString(entry[56..]).TrimEnd('\0');
            if (name.Contains('\0') || string.IsNullOrWhiteSpace(name)) throw new IOException("Prepared partition name is missing or malformed.");
            partitions.Add(new(i + 1, name, type, partId, offset, bytes, BinaryPrimitives.ReadUInt64LittleEndian(entry[48..])));
            end = checked(offset + bytes);
        }
        if (partitions.Select(p => p.Id).Distinct().Count() != partitions.Count) throw new IOException("Duplicate prepared partition GUID.");
        var layout = new PreparedDisk(id, size, partitions.ToArray());
        if (!layout.System.Select(p => p.Name).SequenceEqual(PreparedDisk.Roles)) throw new IOException("Prepared image must contain exactly the eight SteamOS roles in order.");
        var types = new[] {
            "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7",
            "4f68bce3-e8cd-4db1-96e7-fbcaf984b709", "4f68bce3-e8cd-4db1-96e7-fbcaf984b709",
            "4d21b016-b534-45c2-a9fb-5c16e091fd2d", "4d21b016-b534-45c2-a9fb-5c16e091fd2d", "933ac7e1-2eb4-4f13-b844-0e14e2aef915" };
        for (var i = 0; i < types.Length; i++)
            if (layout.System[i].Type != Guid.Parse(types[i])) throw new IOException("Prepared role/type mismatch.");
        if (layout.Protected.Any(p => p.Offset + p.Size > layout.System[0].Offset)) throw new IOException("Protected partitions must precede the selected SteamOS range.");
        return layout;
    }
    public void Dispose() => Stream.Dispose();
}

// All mutating Windows handles are obtained from a newly created or receipted owned VHD.
// Production physical-device execution deliberately has no entry point here.
public static class OwnedPartitionLayout
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(SafeFileHandle handle, uint code, byte[]? input, uint inputLength, byte[]? output, uint outputLength, out uint returned, IntPtr overlapped);
    private static void Control(FileStream disk, uint code, byte[]? input)
    {
        if (!DeviceIoControl(disk.SafeFileHandle, code, input, (uint)(input?.Length ?? 0), null, 0, out _, IntPtr.Zero))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Owned partition layout operation");
    }
    public static void Refresh(VirtualMediaDisk owned)
    {
        using var raw = owned.OpenDevice(); raw.Flush(true); Control(raw, 0x70140, null);
    }
    public static void Initialize(VirtualMediaDisk owned, PreparedDisk prepared, PreparedPartition[] initial)
    {
        if (owned.Size != prepared.Size) throw new IOException("Prepared and owned capacity differ.");
        using (var raw = owned.OpenDevice())
        {
            var before = NativeMediaDevice.ReadLayout(raw.SafeFileHandle, owned.Size);
            if (before.Partitions.Length != 0 || before.DiskId != Guid.Empty) throw new IOException("Only a freshly blank owned VHD may be initialized.");
            var create = new byte[24]; BinaryPrimitives.WriteUInt32LittleEndian(create, 1);
            prepared.Id.TryWriteBytes(create.AsSpan(4, 16)); BinaryPrimitives.WriteUInt32LittleEndian(create.AsSpan(20), 128);
            Control(raw, 0x7c058, create);
        }
        Refresh(owned);
        Set(owned, prepared, initial);
    }
    private static byte[] Encode(FileStream raw, PreparedDisk prepared, PreparedPartition[] parts)
    {
        var current = NativeMediaIo.Query(raw.SafeFileHandle, 0x70050, 1024 * 1024, 48);
        if (BitConverter.ToUInt32(current) != 1 || new Guid(current.AsSpan(8, 16)) != prepared.Id) throw new IOException("Owned GPT identity differs.");
        var bytes = new byte[48 + 144 * parts.Length]; current.AsSpan(0, 48).CopyTo(bytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4), (uint)parts.Length);
        var start = BitConverter.ToInt64(current, 24); var usable = BitConverter.ToInt64(current, 32); long previous = start;
        for (var i = 0; i < parts.Length; i++)
        {
            var p = parts[i];
            if (p.Number != i + 1 || p.Id == Guid.Empty || p.Type == Guid.Empty || p.Offset < previous || p.Size <= 0
                || p.Size > prepared.Size - p.Offset || p.Offset < start || p.Offset + p.Size > start + usable || p.Name.Length > 36)
                throw new IOException("Native target partition plan is invalid.");
            var at = 48 + i * 144;
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(at), 1);
            BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(at + 8), p.Offset);
            BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(at + 16), p.Size);
            BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(at + 24), (uint)p.Number);
            bytes[at + 28] = 1;
            p.Type.TryWriteBytes(bytes.AsSpan(at + 32, 16)); p.Id.TryWriteBytes(bytes.AsSpan(at + 48, 16));
            BinaryPrimitives.WriteUInt64LittleEndian(bytes.AsSpan(at + 64), p.Attributes);
            Encoding.Unicode.GetBytes(p.Name).CopyTo(bytes, at + 72); previous = p.Offset + p.Size;
        }
        return bytes;
    }
    private static void Set(VirtualMediaDisk owned, PreparedDisk prepared, PreparedPartition[] parts)
    {
        using (var raw = owned.OpenDevice()) Control(raw, 0x7c054, Encode(raw, prepared, parts));
        Refresh(owned); Require(owned, prepared.Id, parts);
    }
    public static void Require(VirtualMediaDisk owned, Guid id, PreparedPartition[] parts)
    {
        using var raw = owned.OpenDevice(); var layout = NativeMediaDevice.ReadLayout(raw.SafeFileHandle, owned.Size);
        if (layout.Style != 1 || layout.DiskId != id || !layout.Partitions.SequenceEqual(parts.Select(p => p.Native)))
            throw new IOException("Native partition identity/range differs from prepared plan.");
        var bytes = NativeMediaIo.Query(raw.SafeFileHandle, 0x70050, 1024 * 1024, 48);
        for (var i = 0; i < parts.Length; i++)
            if (BitConverter.ToUInt64(bytes, 48 + i * 144 + 64) != parts[i].Attributes
                || Encoding.Unicode.GetString(bytes, 48 + i * 144 + 72, 72).TrimEnd('\0') != parts[i].Name)
                throw new IOException("Native partition name/attributes differ from prepared plan.");
    }
    public static void Append(VirtualMediaDisk owned, PreparedDisk prepared, InstallationTargetKind kind)
    {
        var expected = kind == InstallationTargetKind.InternalShared ? prepared.Protected : [];
        Require(owned, prepared.Id, expected);
        // Retain the complete Windows-provided existing entry bytes, including
        // attributes/name/service fields, when appending to the owned shared fixture.
        using (var raw = owned.OpenDevice())
        {
            var original = NativeMediaIo.Query(raw.SafeFileHandle, 0x70050, 1024 * 1024, 48);
            var next = Encode(raw, prepared, prepared.For(kind));
            original.AsSpan(48, expected.Length * 144).CopyTo(next.AsSpan(48));
            for (var i = 0; i < expected.Length; i++) next[48 + i * 144 + 28] = 0;
            Control(raw, 0x7c054, next);
        }
        Refresh(owned); Require(owned, prepared.Id, prepared.For(kind));
    }
}

public sealed class PartitionVolumeLocks : IDisposable
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(SafeFileHandle handle, uint code, IntPtr input, uint inputLength, IntPtr output, uint outputLength, out uint returned, IntPtr overlapped);
    private readonly List<SafeFileHandle> handles = [];
    public int Count => handles.Count;
    private static NativeVolume[] Selected(VirtualMediaDisk owned, PreparedPartition[] parts)
    {
        var number = owned.BoundDiskNumber();
        return NativeVolumes.FindForDisk(number, owned.Size).Where(v =>
        {
            var e = v.Extents.Single();
            var overlaps = parts.Where(p => e.Offset < p.Offset + p.Size && p.Offset < e.Offset + e.Size).ToArray();
            if (overlaps.Length == 0) return false;
            if (overlaps.Length != 1 || e.Offset != overlaps[0].Offset || e.Size != overlaps[0].Size)
                throw new IOException("A target volume does not match one complete selected partition.");
            return true;
        }).ToArray();
    }
    public static PartitionVolumeLocks Acquire(VirtualMediaDisk owned, PreparedPartition[] parts)
    {
        var result = new PartitionVolumeLocks(); var number = owned.BoundDiskNumber();
        using var raw = owned.OpenDevice(); var before = NativeMediaDevice.ReadLayout(raw.SafeFileHandle, owned.Size);
        if (parts.Length == 0 || parts.Select(p => p.Id).Distinct().Count() != parts.Length
            || parts.Any(p => !before.Partitions.Contains(p.Native))) throw new IOException("Partition lock selection differs from native GPT.");
        var selected = Selected(owned, parts);
        var windowsVolumes = parts.Where(p => p.Type == Guid.Parse("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
            || p.Type == Guid.Parse("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7")).ToArray();
        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (windowsVolumes.Any(p => !selected.Any(v => v.Extents[0].Offset == p.Offset && v.Extents[0].Size == p.Size)))
        {
            if (DateTime.UtcNow >= deadline) throw new IOException("Selected Windows GUID volumes have not arrived; refuse before writing.");
            Thread.Sleep(100); selected = Selected(owned, parts);
        }
        try
        {
            foreach (var volume in selected)
            {
                var handle = CreateFile(volume.Path[..^1], 0xc0000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
                if (handle.IsInvalid) { var error = Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(error, "Open selected target volume"); }
                try
                {
                    if (!NativeVolumes.ReadExtents(handle).SequenceEqual(volume.Extents)) throw new IOException("Target volume extent changed.");
                    for (var attempt = 0; ; attempt++)
                    {
                        try { Control(handle, 0x90018); break; }
                        catch (Win32Exception error) when (error.NativeErrorCode == 5 && attempt < 9)
                        {
                            // A new Windows volume can still be under a transient
                            // filesystem probe. Never dismount or write without its lock.
                            Thread.Sleep(100);
                            if (!NativeVolumes.ReadExtents(handle).SequenceEqual(volume.Extents))
                                throw new IOException("Target extent changed during bounded lock retry.");
                        }
                    }
                    result.handles.Add(handle); handle = null!;
                }
                finally { handle?.Dispose(); }
            }
            if (number != owned.BoundDiskNumber() || !NativeMediaDevice.SameLayout(before, NativeMediaDevice.ReadLayout(raw.SafeFileHandle, owned.Size))
                || !Selected(owned, parts).SequenceEqual(selected, NativeVolumeEquality.Instance)) throw new IOException("Target binding changed while locking partitions.");
            foreach (var handle in result.handles) Control(handle, 0x90020);
            return result;
        }
        catch { result.Dispose(); throw; }
    }
    private sealed class NativeVolumeEquality : IEqualityComparer<NativeVolume>
    {
        public static readonly NativeVolumeEquality Instance = new();
        public bool Equals(NativeVolume? a, NativeVolume? b) => a != null && b != null && a.Path == b.Path && a.Extents.SequenceEqual(b.Extents);
        public int GetHashCode(NativeVolume value) => StringComparer.OrdinalIgnoreCase.GetHashCode(value.Path);
    }
    private static void Control(SafeFileHandle handle, uint code)
    {
        if (!DeviceIoControl(handle, code, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Lock/dismount selected deployment partition");
    }
    public void Dispose()
    {
        foreach (var handle in handles.AsEnumerable().Reverse())
        {
            try { DeviceIoControl(handle, 0x9001c, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero); }
            finally { handle.Dispose(); }
        }
        handles.Clear();
    }
}

public static class PartitionDeployment
{
    // The same explicit ranges drive the write and its durable readback. A zero
    // source block within a selected range is always written to the destination.
    internal static async Task CopyRangesAsync(FileStream source, FileStream target, long sourceOffset, long targetOffset, long length,
        long capacity, IReadOnlyList<CopyExtent> ranges, Action<MediaProgress> report, CancellationToken token)
    {
        var total = RequireRanges(source, sourceOffset, targetOffset, length, capacity, ranges);
        long written = 0;
        var input = new byte[4 * 1024 * 1024];
        try
        {
            foreach (var range in ranges)
            {
                source.Position = checked(sourceOffset + range.Offset); target.Position = checked(targetOffset + range.Offset);
                for (long offset = 0; offset < range.Length;)
                {
                    token.ThrowIfCancellationRequested(); var count = (int)Math.Min(input.Length, range.Length - offset);
                    await source.ReadExactlyAsync(input.AsMemory(0, count), token); token.ThrowIfCancellationRequested();
                    await target.WriteAsync(input.AsMemory(0, count), token); offset += count; written += count;
                    report(new("writing", written, 0, total));
                }
            }
            target.Flush(true);
            await CompareRangesAsync(source, target, sourceOffset, targetOffset, length, capacity, ranges,
                verified => report(new("verifying", written, verified, total)), token);
            token.ThrowIfCancellationRequested(); target.Flush(true);
        }
        catch (Exception original)
        {
            try { target.Flush(true); }
            catch (Exception flush) { throw new AggregateException("Partition operation and final flush failed.", original, flush); }
            throw;
        }
    }
    private static long RequireRanges(FileStream source, long sourceOffset, long targetOffset, long length, long capacity, IReadOnlyList<CopyExtent> ranges)
    {
        if (sourceOffset < 0 || targetOffset < 1048576 || length <= 0 || sourceOffset % 512 != 0 || targetOffset % 512 != 0 || length % 512 != 0
            || sourceOffset > source.Length || length > source.Length - sourceOffset || capacity < 1048576
            || targetOffset > capacity - 1048576 || length > capacity - targetOffset - 1048576 || ranges.Count is < 1 or > 8192)
            throw new IOException("Partition copy range is outside supported aligned data bounds.");
        long end = 0, total = 0;
        for (var i = 0; i < ranges.Count; i++)
        {
            var range = ranges[i];
            if (range.Offset < 0 || range.Length <= 0 || range.Offset % 512 != 0 || range.Length % 512 != 0
                || range.Offset > length || range.Length > length - range.Offset || i > 0 && range.Offset < end)
                throw new IOException("Invalid partition copy extent.");
            end = range.Offset + range.Length; total = checked(total + range.Length);
        }
        return total;
    }
    internal static async Task CompareRangesAsync(FileStream source, FileStream target, long sourceOffset, long targetOffset, long length,
        long capacity, IReadOnlyList<CopyExtent> ranges, Action<long> report, CancellationToken token)
    {
        RequireRanges(source, sourceOffset, targetOffset, length, capacity, ranges);
        var input = new byte[4 * 1024 * 1024]; var output = new byte[input.Length]; long verified = 0;
        foreach (var range in ranges)
        {
            source.Position = checked(sourceOffset + range.Offset); target.Position = checked(targetOffset + range.Offset);
            for (long offset = 0; offset < range.Length;)
            {
                token.ThrowIfCancellationRequested(); var count = (int)Math.Min(input.Length, range.Length - offset);
                await source.ReadExactlyAsync(input.AsMemory(0, count), token); await target.ReadExactlyAsync(output.AsMemory(0, count), token);
                if (!input.AsSpan(0, count).SequenceEqual(output.AsSpan(0, count)))
                {
                    var first = 0; while (first < count && input[first] == output[first]) first++;
                    throw new CompletedRangeMismatchException(range.Offset + offset + first);
                }
                offset += count; verified += count; report(verified);
            }
        }
        token.ThrowIfCancellationRequested();
    }
    public static async Task CopyRangeAsync(FileStream source, FileStream target, long sourceOffset, long targetOffset, long length,
        long capacity, Action<MediaProgress> report, CancellationToken token)
    {
        if (sourceOffset < 0 || targetOffset < 1024 * 1024 || length <= 0 || sourceOffset % 512 != 0 || targetOffset % 512 != 0 || length % 512 != 0
            || length > source.Length - sourceOffset || length > capacity - targetOffset - 1024 * 1024)
            throw new IOException("Partition copy range is outside supported aligned data bounds.");
        long written = 0, verified = 0; var input = new byte[4 * 1024 * 1024]; var output = new byte[input.Length];
        try
        {
            source.Position = sourceOffset; target.Position = targetOffset;
            while (written < length)
            {
                token.ThrowIfCancellationRequested(); var count = (int)Math.Min(input.Length, length - written);
                await source.ReadExactlyAsync(input.AsMemory(0, count), token); token.ThrowIfCancellationRequested();
                await target.WriteAsync(input.AsMemory(0, count), token); written += count; report(new("writing", written, 0, length));
            }
            target.Flush(true); source.Position = sourceOffset; target.Position = targetOffset;
            while (verified < length)
            {
                token.ThrowIfCancellationRequested(); var count = (int)Math.Min(input.Length, length - verified);
                await source.ReadExactlyAsync(input.AsMemory(0, count), token); await target.ReadExactlyAsync(output.AsMemory(0, count), token);
                if (!input.AsSpan(0, count).SequenceEqual(output.AsSpan(0, count))) throw new IOException("Partition readback differs at " + verified);
                verified += count; report(new("verifying", written, verified, length));
            }
            token.ThrowIfCancellationRequested(); target.Flush(true);
        }
        catch (Exception original)
        {
            try { target.Flush(true); }
            catch (Exception flush) { throw new AggregateException("Partition operation and final flush failed.", original, flush); }
            throw;
        }
    }
    public static void RequireSourceOutsideTargets(FileStream source, int number, PreparedPartition[] writes)
    {
        var volume = NativeVolumes.FromOpenFile(source);
        if (volume.Extents.Length != 1 || volume.Extents.Any(e => e.DiskNumber == number
            && writes.Any(p => e.Offset < p.Offset + p.Size && p.Offset < e.Offset + e.Size)))
            throw new IOException("Prepared source volume overlaps target partitions or is spanned.");
    }
    // Recovery never guesses physical disk numbers or recreates a partial GPT.
    public static async Task ResumeOwnedAsync(PreparedDiskImage image, InstallationTargetKind kind,
        string statePath, Action<string> log, CancellationToken token)
    {
        MediaSource.Ordinary(statePath, InstallerWorkspace.DirectoryPath);
        using var state = ReadState(statePath); var root = state.RootElement;
        if (root.GetProperty("schema").GetInt32() != 2) throw new IOException("This journal predates recoverable owned VHDs.");
        var path = root.GetProperty("target_vhd").GetString() ?? throw new IOException("Missing target VHD.");
        if (Path.GetFullPath(statePath) != Path.Combine(Path.GetDirectoryName(path)!, "state.json"))
            throw new IOException("Recovery journal and VHD directory differ.");
        if (!Enum.IsDefined(kind) || root.GetProperty("kind").GetString() != kind.ToString()
            || root.GetProperty("source").Deserialize<MediaSource>() != image.Identity)
            throw new IOException("Recovery journal source or kind differs.");
        token.ThrowIfCancellationRequested();
        using var owned = VirtualMediaDisk.ReopenOwned(path, image.Layout.Size, root.GetProperty("target_id").GetGuid());
        await ApplyOwnedAsync(image, owned, kind, statePath, log, token, resume: true);
    }
    private static JsonDocument ReadState(string path)
    {
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length > 64 * 1024) throw new IOException("Oversized deployment journal.");
        return JsonDocument.Parse(file);
    }
    public static async Task VerifyRangeAsync(FileStream source, FileStream target, PreparedPartition part,
        long capacity, Action<long> report, CancellationToken token)
    {
        if (part.Offset < 1024 * 1024 || part.Size <= 0 || part.Offset % 512 != 0 || part.Size % 512 != 0
            || part.Size > source.Length - part.Offset || part.Size > capacity - part.Offset - 1024 * 1024)
            throw new IOException("Recovery verification range exceeds data bounds.");
        var first = new byte[4 * 1024 * 1024]; var second = new byte[first.Length];
        source.Position = target.Position = part.Offset;
        for (long read = 0; read < part.Size;)
        {
            token.ThrowIfCancellationRequested(); var count = (int)Math.Min(first.Length, part.Size - read);
            await source.ReadExactlyAsync(first.AsMemory(0, count), token);
            await target.ReadExactlyAsync(second.AsMemory(0, count), token);
            if (!first.AsSpan(0, count).SequenceEqual(second.AsSpan(0, count)))
                throw new IOException("Previously completed partition differs: " + part.Name + " at " + read);
            read += count; report(read);
        }
        token.ThrowIfCancellationRequested();
    }
    public static async Task ApplyOwnedAsync(PreparedDiskImage image, VirtualMediaDisk owned, InstallationTargetKind kind,
        string statePath, Action<string> log, CancellationToken token, bool resume = false)
    {
        if (!Enum.IsDefined(kind)) throw new IOException("Unknown installation target kind.");
        image.Recheck(); token.ThrowIfCancellationRequested();
        var targets = image.Layout.For(kind).Where(p => PreparedDisk.Roles.Contains(p.Name)).ToArray();
        RequireSourceOutsideTargets(image.Stream, owned.BoundDiskNumber(), targets);
        MediaSource.Ordinary(statePath, InstallerWorkspace.DirectoryPath, false);
        if (File.Exists(statePath) != resume) throw new IOException("Existing deployment journals require explicit recovery; new jobs require an unused path.");
        MediaSource.Ordinary(statePath + ".lock", InstallerWorkspace.DirectoryPath, false);
        using var lease = new FileStream(statePath + ".lock", FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.DeleteOnClose);
        var complete = new List<string>(); string phase = "preflight", status = "in_progress"; string? error = null;
        long written = 0, verified = 0; var attempt = 1;
        if (resume)
        {
            using var previous = ReadState(statePath); var root = previous.RootElement;
            var recorded = root.GetProperty("completed").EnumerateArray().Select(p => p.GetString() ?? "").ToArray();
            if (root.GetProperty("schema").GetInt32() != 2 || root.GetProperty("kind").GetString() != kind.ToString()
                || root.GetProperty("source").Deserialize<MediaSource>() != image.Identity
                || root.GetProperty("target_vhd").GetString() != owned.PathOnHost || root.GetProperty("target_id").GetGuid() != owned.Id
                || root.GetProperty("boot_ready").GetBoolean()
                || root.GetProperty("status").GetString() is not ("in_progress" or "cancelled" or "failed" or "complete")
                || recorded.Length > targets.Length || !recorded.SequenceEqual(targets.Take(recorded.Length).Select(p => p.Name)))
                throw new IOException("Recovery journal source, target, mode, status or completed prefix differs.");
            if (root.GetProperty("status").GetString() == "complete" && recorded.Length != targets.Length)
                throw new IOException("Incomplete partition list marked complete.");
            attempt = checked(root.GetProperty("attempt").GetInt32() + 1);
            if (attempt < 2 || attempt > 1000) throw new IOException("Invalid recovery attempt.");
            OwnedPartitionLayout.Require(owned, image.Layout.Id, image.Layout.For(kind));
            complete.AddRange(recorded);
            var audit = statePath + ".before-resume-" + Guid.NewGuid().ToString("N") + ".json";
            using var record = new FileStream(audit, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            using (var writer = new Utf8JsonWriter(record)) { previous.WriteTo(writer); writer.Flush(); }
            record.Flush(true);
        }
        void Save()
        {
            var temporary = statePath + ".tmp";
            MediaSource.Ordinary(temporary, InstallerWorkspace.DirectoryPath, false);
            using (var file = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                JsonSerializer.Serialize(file, new { schema = 2, attempt, status, phase, kind = kind.ToString(), source = image.Identity,
                    target_vhd = owned.PathOnHost, target_id = owned.Id, completed = complete, written, verified, error,
                    boot_ready = false, scope = "Owned receipted VHD partition deployment only; no host firmware modification or physical acceptance" });
                file.Flush(true);
            }
            File.Move(temporary, statePath, true);
        }
        try
        {
            Save(); token.ThrowIfCancellationRequested();
            if (!resume) { phase = "creating-partitions"; Save(); OwnedPartitionLayout.Append(owned, image.Layout, kind); }
            phase = "locking-targets"; Save();
            using var locks = PartitionVolumeLocks.Acquire(owned, targets);
            using var target = owned.OpenDevice();
            var primary = new byte[34 * 512]; target.Position = 0; target.ReadExactly(primary);
            // A full stream buffer stays inside the native device at its tail.
            var backup = new byte[1024 * 1024]; target.Position = owned.Size - backup.Length; target.ReadExactly(backup);
            // Verify the entire completed prefix BEFORE any new content write.
            foreach (var p in targets.Take(complete.Count))
            {
                phase = "rechecking:" + p.Name; written = verified = 0; Save(); image.Recheck();
                log("PARTITION_RECHECKING=" + p.Name);
                await VerifyRangeAsync(image.Stream, target, p, owned.Size, bytes => verified = bytes, token);
                log("PARTITION_RECHECKED=" + p.Name);
            }
            foreach (var p in targets.Skip(complete.Count).ToArray())
            {
                phase = p.Name; written = verified = 0; Save(); image.Recheck();
                OwnedPartitionLayout.Require(owned, image.Layout.Id, image.Layout.For(kind));
                RequireSourceOutsideTargets(image.Stream, owned.BoundDiskNumber(), targets);
                var sourcePart = image.Layout.System.Single(s => s.Id == p.Id);
                var lastSaved = DateTime.UtcNow; var lastProgressStage = "";
                await CopyRangeAsync(image.Stream, target, sourcePart.Offset, p.Offset, p.Size, owned.Size,
                    progress =>
                    {
                        written = progress.Written; verified = progress.Verified;
                        if (progress.Stage != lastProgressStage || (DateTime.UtcNow - lastSaved).TotalSeconds >= 2)
                        {
                            Save(); lastSaved = DateTime.UtcNow; lastProgressStage = progress.Stage;
                            log($"PARTITION_PROGRESS={p.Name}:{progress.Stage}:{written}:{verified}:{p.Size}");
                        }
                    }, token);
                var check = new byte[primary.Length]; target.Position = 0; target.ReadExactly(check);
                if (!check.AsSpan().SequenceEqual(primary)) throw new IOException("Partition write changed primary GPT.");
                check = new byte[backup.Length]; target.Position = owned.Size - check.Length; target.ReadExactly(check);
                if (!check.AsSpan().SequenceEqual(backup)) throw new IOException("Partition write changed backup GPT.");
                complete.Add(p.Name); Save(); log("PARTITION_DEPLOYED=" + p.Name);
            }
            OwnedPartitionLayout.Require(owned, image.Layout.Id, image.Layout.For(kind));
            phase = "partition-content-complete"; status = "complete"; Save();
        }
        catch (Exception ex)
        {
            status = ex is OperationCanceledException ? "cancelled" : "failed"; error = ex.ToString(); Save(); throw;
        }
    }
}
