using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class PreparedCapacity
{
    internal static async Task<string> ExpandAsync(string image, string directory, long capacity, Action<string> log, CancellationToken token)
    {
        PreparedDisk before;
        using (var source = new PreparedDiskImage(image)) before = source.Layout;
        var system = before.System;
        var used = checked(system[^1].Offset + system[^1].Size - system[0].Offset);
        if (capacity < PartitionInventory.Minimum || capacity % PartitionInventory.MiB != 0 || capacity < used)
            throw new IOException("安装容量小于系统布局，或未按 MiB 对齐。 / Invalid installation capacity.");
        if (capacity == used) return image;
        // Only resize a session-owned copy; a selected prepared image stays immutable.
        if (!string.Equals(Path.GetDirectoryName(Path.GetFullPath(image)), Path.GetFullPath(directory), StringComparison.OrdinalIgnoreCase))
        {
            var copy = Path.Combine(directory, "capacity-prepared.img");
            await RawImageStaging.ConvertAsync(image, copy, log, token);
            image = copy;
        }
        var size = Math.Max(before.Size, checked(system[0].Offset + capacity + PartitionInventory.MiB));
        MediaSource.Ordinary(image, InstallationController.Work);
        var sparse = (File.GetAttributes(image) & FileAttributes.SparseFile) != 0;
        MediaSpace.RequireAvailable(directory, checked((sparse ? 0ul : (ulong)(size - before.Size)) + 8ul * PartitionInventory.GiB));
        using (var file = new FileStream(image, FileMode.Open, FileAccess.Write, FileShare.None)) { file.SetLength(size); file.Flush(true); }
        var selection = JsonSerializer.Serialize(new { capacity, disk_id = before.Id,
            partitions = before.Partitions.Select(p => new { number = p.Number, name = p.Name, start = p.Offset / 512, size = p.Size / 512, uuid = p.Id, type = p.Type }) });
        await Backend.GuestAsync("resize-prepared", image, true, log, token, selection: selection);
        using var result = new PreparedDiskImage(image);
        var after = result.Layout;
        var expectedHome = system[^1] with { Size = checked(system[^1].Size + capacity - used) };
        if (after.Id != before.Id || after.Size != size || !after.Partitions.SequenceEqual(before.Partitions.Select(p => p.Name == "home" ? expectedHome : p)))
            throw new IOException("Expanded image differs from the selected layout.");
        return image;
    }
}
