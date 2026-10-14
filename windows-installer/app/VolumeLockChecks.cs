using System.ComponentModel;
using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public static class VolumeLockChecks
{
    private sealed record VolumeSnapshot(int DiskNumber, long Size, string[] Paths);
    public static async Task<string> RunAsync()
    {
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "volume-lock-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "media.vhd"); var events = new List<string>(); string volume;
        using (var disk = new VirtualMediaDisk(path, 128 * 1024 * 1024))
        {
            var json = await Backend.PowerShellAsync("vhd-test-volumes.ps1", ["-VhdPath", path, "-Prepare", "-Count", "2"], _ => { }, CancellationToken.None);
            var snapshot = JsonSerializer.Deserialize<VolumeSnapshot>(json) ?? throw new IOException("Owned VHD volume query failed.");
            if (snapshot.DiskNumber != disk.BoundDiskNumber() || snapshot.Size != disk.Size || snapshot.Paths.Length != 2) throw new IOException("Owned VHD query/binding differs.");
            volume = snapshot.Paths[0]; var sentinel = snapshot.Paths[1] + "preserved.txt"; var first = snapshot.Paths[0] + "first-preserved.txt"; File.WriteAllText(first, "first owned VHD volume\n"); File.WriteAllText(sentinel, "owned VHD volume data\n");
            using (var held = new FileStream(sentinel, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            {
                var refused = false;
                try { using var unexpected = MediaVolumeLocks.AcquireForOwnedVhd(disk, snapshot.Paths); }
                catch (Win32Exception error) when (error.Message.Contains("Lock owned VHD volume", StringComparison.Ordinal)) { refused = true; }
                if (!refused) throw new IOException("Busy owned volume was not refused before dismount.");
                if (File.ReadAllText(sentinel) != "owned VHD volume data\n" || File.ReadAllText(first) != "first owned VHD volume\n") throw new IOException("Busy lock refusal changed data or left earlier volume locked.");
                events.Add("second-busy-volume-refused-before-explicit-dismount-first-lock-released");
            }
            using (var locked = MediaVolumeLocks.AcquireForOwnedVhd(disk, snapshot.Paths))
            {
                if (locked.LockedCount != 2) throw new IOException("Owned volume lock was not held.");
                events.Add("native-extents-bound-all-locks-before-dismount");
            }
            if (File.ReadAllText(sentinel) != "owned VHD volume data\n" || File.ReadAllText(first) != "first owned VHD volume\n") throw new IOException("Unlock/remount did not preserve both owned volumes.");
            events.Add("handles-closed-unlock-remount-sentinel-preserved");
        }
        events.Add("owned-vhd-detached");
        File.WriteAllText(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new { passed = true, path, volume, events,
            scope = "Only newly created 128MiB VHD initialized/formatted with no drive letters. Native GUID-volume extents bind to its live VHD handle; second-volume busy-file refusal with earlier lock release, both-volume lock/dismount/unlock and preserved sentinels/remount verified. No existing or physical USB volume dismounted." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
    public static async Task<string> WriteAsync(string image)
    {
        using var source = MediaSource.Open(image); var identity = MediaSource.FromHandle(image, source);
        if (identity.Length > 128 * 1024 * 1024) throw new IOException("Volume-write lab source is limited to 128MiB.");
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "volume-lock-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "media.vhd"); long written = 0, verified = 0;
        using (var disk = new VirtualMediaDisk(path, 128 * 1024 * 1024))
        {
            var json = await Backend.PowerShellAsync("vhd-test-volumes.ps1", ["-VhdPath", path, "-Prepare", "-Count", "2"], _ => { }, CancellationToken.None);
            var snapshot = JsonSerializer.Deserialize<VolumeSnapshot>(json) ?? throw new IOException("Owned volume write snapshot absent.");
            if (snapshot.DiskNumber != disk.BoundDiskNumber() || snapshot.Size != disk.Size || snapshot.Paths.Length != 2) throw new IOException("Wrong owned volume write binding.");
            NativeVolumes.RequireDifferentSource(source, disk.BoundDiskNumber());
            using var locked = MediaVolumeLocks.AcquireForOwnedVhd(disk, snapshot.Paths);
            using var target = disk.OpenDevice();
            await AlignedMediaCopy.CopyAndVerifyAsync(source, target, identity.Length, disk.Size, progress => { written = progress.Written; verified = progress.Verified; }, () => false);
            if (written != identity.Length || verified != identity.Length || locked.LockedCount != 2) throw new IOException("Raw owned volume write did not preserve all locks through readback.");
        }
        File.WriteAllText(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new { passed = true, path, image, written, verified,
            scope = "New 128MiB owned VHD with two NTFS volumes; native extents bind, both locks held before dismount and throughout actual aligned raw synthetic image write/readback, then close/unlock/detach. Only these new test volumes replaced; no physical USB or system volumes." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
}
