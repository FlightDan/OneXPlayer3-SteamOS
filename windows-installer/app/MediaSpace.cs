using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
namespace OxpInstaller;
public sealed record MediaSpaceInfo(ulong Available, ulong Required);
public static class MediaSpace
{
    public const ulong MinimumWorkspace = 45ul * 1024 * 1024 * 1024;
    public const ulong RecommendedWorkspace = 64ul * 1024 * 1024 * 1024;
    public static ulong Available(string directory)
    {
        if (!GetDiskFreeSpaceEx(directory, out var available, out _, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Read available workspace space");
        return available;
    }
    // Startup budget, not the logical capacities of sparse images. Recheck each
    // export using the source extent map before allocating its destination.
    public static ulong InstallationBudget(bool physical, bool prepared) =>
        MinimumWorkspace + (physical ? 0ul : 80ul * 1024 * 1024 * 1024);
    public static void RequireAvailable(string directory, ulong required)
    {
        var available = Available(directory);
        if (available < required) throw new IOException(PartitionInventory.L(
            $"工作空间不足：可用 {available / 1073741824d:F1} GiB，本阶段需 {required / 1073741824d:F1} GiB。请选择更大的工作目录。",
            $"Workspace space is insufficient: {available / 1073741824d:F1} GiB available, {required / 1073741824d:F1} GiB needed for this stage. Choose another folder."));
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetDiskFreeSpaceEx(string directory, out ulong available, out ulong total, out ulong free);
    public static MediaSpaceInfo Query(string directory, long capacity)
    {
        if (capacity < 16L * 1024 * 1024 || capacity > 32L * 1024 * 1024 * 1024 || capacity % 512 != 0) throw new IOException("Invalid VHD space estimate.");
        if (!GetDiskFreeSpaceEx(directory, out var available, out _, out _)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Read available work-volume space");
        // Worst-case raw payload plus dynamic VHD metadata and work-volume reserve.
        // This is a preflight snapshot, not a reservation against other writers.
        var required = checked((ulong)capacity + 8ul * 1024 * 1024 + 64ul * 1024 * 1024);
        return new(available, required);
    }
    public static MediaSpaceInfo RequirePartitionStaging(string directory, long diskCapacity, int copies = 2)
    {
        if (copies is not (2 or 3) || diskCapacity < 64L * 1024 * 1024 * 1024 || diskCapacity > 512L * 1024 * 1024 * 1024 || diskCapacity % 512 != 0)
            throw new IOException("Invalid partition staging capacity.");
        if (!GetDiskFreeSpaceEx(directory, out var available, out _, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Read available partition staging space");
        var required = checked((ulong)diskCapacity * (ulong)copies + 512ul * 1024 * 1024);
        if (available < required) throw new IOException($"Insufficient partition staging space: {available} bytes available, {required} required.");
        return new(available, required);
    }
    public static MediaSpaceInfo Require(string directory, long capacity)
    {
        var info = Query(directory, capacity);
        if (info.Available < info.Required) throw new IOException($"Insufficient work-volume space: {info.Available} bytes available, {info.Required} required for VHD and reserve.");
        return info;
    }
}
