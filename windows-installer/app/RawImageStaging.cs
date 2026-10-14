using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

internal static class RawImageStaging
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool DeviceIoControl(SafeFileHandle file, uint code, IntPtr input, uint inputSize,
        IntPtr output, uint outputSize, out uint returned, IntPtr overlapped);

    internal static async Task ConvertAsync(string source, string destination, Action<string> log, CancellationToken token)
    {
        MediaSource.Ordinary(destination, InstallationController.Work, false);
        var qemu = Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe");
        using var info = JsonDocument.Parse(await Backend.ProcessAsync(qemu, ["info", "--output=json", source], _ => { }, token));
        var capacity = info.RootElement.GetProperty("virtual-size").GetInt64();
        using var map = JsonDocument.Parse(await Backend.ProcessAsync(qemu, ["map", "--output=json", source], _ => { }, token));
        ulong allocated = 0;
        foreach (var extent in map.RootElement.EnumerateArray())
            if (!extent.TryGetProperty("zero", out var zero) || !zero.GetBoolean())
                allocated = checked(allocated + extent.GetProperty("length").GetUInt64());
        const ulong reserve = 8ul * 1024 * 1024 * 1024;
        bool sparse;
        using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            sparse = DeviceIoControl(output.SafeFileHandle, 0x900c4, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);
            MediaSpace.RequireAvailable(Path.GetDirectoryName(destination)!, checked((sparse ? allocated : (ulong)capacity) + reserve));
            output.SetLength(capacity);
        }
        log($"Image staging: logical {capacity / 1073741824d:F1} GiB; mapped data upper bound {allocated / 1073741824d:F1} GiB; sparse={sparse}.");
        // Keep the explicitly sparse file. -n prevents qemu from recreating it.
        await Backend.ProcessAsync(qemu, ["convert", "-n", "--target-is-zero", "-S", "4k", "-O", "raw", source, destination], log, token);
    }
}
