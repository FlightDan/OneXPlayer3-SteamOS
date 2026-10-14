using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public static class NativeBindingChecks
{
    private sealed record VolumeSnapshot(int DiskNumber, long Size, string[] Paths);
    public static async Task<string> RunAsync(string image)
    {
        using var source = MediaSource.Open(image); var sourceIdentity = MediaSource.FromHandle(image, source);
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "volume-lock-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "media.vhd"); var events = new List<string>(); NativeDiskInfo native; NativeLayout layout; NativeVolume sourceVolume; NativeVolume[] volumes; UsbReviewOperation refused;
        using (var disk = new VirtualMediaDisk(path, 128 * 1024 * 1024))
        {
            using (var blank = disk.OpenDevice())
            {
                var rawLayout = NativeMediaDevice.ReadLayout(blank.SafeFileHandle, disk.Size);
                var rawVolumes = NativeVolumes.FindForDisk(disk.BoundDiskNumber(), disk.Size);
                var rawWindows = (await UsbMediaPlanning.ReadAsync(image, CancellationToken.None)).Disks.Single(d => d.Number == disk.BoundDiskNumber());
                File.WriteAllText(Path.Combine(directory, "blank-native-state.json"), JsonSerializer.Serialize(new { rawLayout, rawVolumes, windowsStyle = rawWindows.Style }, new JsonSerializerOptions { WriteIndented = true }));
                if (rawWindows.Style != "RAW" || rawLayout.Partitions.Length != 0 || rawVolumes.Length != 0) throw new IOException("Fresh RAW VHD native layout/volume discovery is not empty.");
                NativeMediaDevice.MatchReviewedLayout(rawWindows, rawLayout);
                events.Add("actual-blank-raw-layout-and-zero-volume-discovery");
            }
            var json = await Backend.PowerShellAsync("vhd-test-volumes.ps1", ["-VhdPath", path, "-Prepare", "-Count", "2"], _ => { }, CancellationToken.None);
            var snapshot = JsonSerializer.Deserialize<VolumeSnapshot>(json) ?? throw new IOException("Native review fixture query missing.");
            if (snapshot.DiskNumber != disk.BoundDiskNumber() || snapshot.Size != disk.Size || snapshot.Paths.Length != 2) throw new IOException("Wrong native review fixture binding.");
            var inventory = await UsbMediaPlanning.ReadAsync(image, CancellationToken.None);
            var reviewed = inventory.Disks.Single(d => d.Number == disk.BoundDiskNumber());
            using (var raw = disk.OpenDevice())
            {
                native = NativeMediaDevice.Read(raw.SafeFileHandle); layout = NativeMediaDevice.ReadLayout(raw.SafeFileHandle, disk.Size);
                if (native.Number != snapshot.DiskNumber || native.Bus != 15 || native.SectorSize != 512 || native.Size != disk.Size) throw new IOException("Native owned device differs from Windows metadata.");
                NativeMediaDevice.MatchReviewedLayout(reviewed, layout); events.Add("actual-native-number-capacity-sector-bus-layout-match");
                var denied = false;
                try { NativeMediaDevice.MatchReviewedLayout(reviewed with { Partitions = reviewed.Partitions.Select((p, i) => i == 0 ? p with { Offset = p.Offset + 512 } : p).ToArray() }, layout); }
                catch (IOException) { denied = true; }
                if (!denied) throw new IOException("Native changed partition range was accepted."); events.Add("reviewed-range-mismatch-refused-against-real-layout");
            }
            volumes = NativeVolumes.RequireComplete(snapshot.DiskNumber, snapshot.Size, snapshot.Paths);
            if (volumes.Length != 2 || volumes.Any(v => v.Extents.Length != 1 || !layout.Partitions.Any(p => p.Offset == v.Extents[0].Offset && p.Size == v.Extents[0].Size))) throw new IOException("Native GUID-volume discovery differs from actual partition ranges.");
            events.Add("complete-native-guid-volume-discovery-two-exact-extents");
            sourceVolume = NativeVolumes.RequireDifferentSource(source, snapshot.DiskNumber);
            if (sourceVolume.Extents[0].DiskNumber != inventory.SourceDiskNumber) throw new IOException("Source handle/native volume differs from Windows source mapping.");
            events.Add("opened-image-source-volume-bound-to-different-actual-disk");
            var first = snapshot.Paths[0] + "native-source-sentinel.txt"; var second = snapshot.Paths[1] + "native-second-sentinel.txt";
            File.WriteAllText(first, "native source guard\n"); File.WriteAllText(second, "native second guard\n");
            using (var onTarget = new FileStream(first, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                var denied = false; try { NativeVolumes.RequireDifferentSource(onTarget, snapshot.DiskNumber); } catch (IOException error) when (error.Message.StartsWith("Source image volume", StringComparison.Ordinal)) { denied = true; }
                if (!denied) throw new IOException("Actual source on selected target disk was accepted.");
            }
            events.Add("actual-source-on-target-disk-refused");
            var incomplete = false;
            try { using var unexpected = MediaVolumeLocks.AcquireForOwnedVhd(disk, [snapshot.Paths[0]]); } catch (IOException error) when (error.Message.StartsWith("Target volume list is incomplete", StringComparison.Ordinal)) { incomplete = true; }
            if (!incomplete || File.ReadAllText(first) != "native source guard\n" || File.ReadAllText(second) != "native second guard\n") throw new IOException("Missing second volume was not refused before lock/dismount.");
            events.Add("omitted-real-second-volume-refused-before-lock-or-dismount");
            var fakeUsb = reviewed with { Bus = "USB" }; var nativeDenied = false;
            try { using var unexpected = NativeMediaDevice.OpenReviewedUsbReadOnly(fakeUsb); } catch (IOException error) when (error.Message.StartsWith("Native USB handle identity", StringComparison.Ordinal)) { nativeDenied = true; }
            if (!nativeDenied) throw new IOException("Native virtual bus was accepted as USB."); events.Add("actual-readonly-native-virtual-bus-refused-as-usb");
            refused = await UsbNativeReview.RunAsync(image, fakeUsb, CancellationToken.None);
            if (refused.Result.Status != "refused" || refused.Result.Error?.Contains("设备总线不是 USB", StringComparison.Ordinal) != true) throw new IOException("Independent readonly helper did not refuse actual non-USB Windows metadata.");
            events.Add("separate-readonly-helper-refuses-actual-non-usb-inventory");
            using (var locks = MediaVolumeLocks.AcquireForOwnedVhd(disk, snapshot.Paths))
                if (locks.LockedCount != 2) throw new IOException("Complete native volume set was not locked.");
            if (File.ReadAllText(first) != "native source guard\n" || File.ReadAllText(second) != "native second guard\n" || MediaSource.FromHandle(image, source) != sourceIdentity) throw new IOException("Readonly native review/lock cleanup changed source or target sentinels.");
            events.Add("complete-volume-lock-layout-reread-unlock-both-sentinels-preserved");
        }
        File.WriteAllText(Path.Combine(directory, "native-binding-result.json"), JsonSerializer.Serialize(new { passed = true, path, native, layout, volumes, sourceVolume, readonly_helper = refused, events,
            scope = "Actual new 128MiB VHD native metadata/partition/complete GUID-volume extents, source on host vs target refusal, missing volume rejection before locks, native virtual-bus rejection, independent readonly helper non-USB refusal and complete lock/reread/cleanup. No physical USB positive case, ordinary-user UAC, existing-disk lock/dismount or raw write." }, new JsonSerializerOptions { WriteIndented = true }));
        return directory;
    }
}