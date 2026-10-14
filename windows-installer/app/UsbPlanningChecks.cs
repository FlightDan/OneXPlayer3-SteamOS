using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public static class UsbPlanningChecks
{
    public static string Run()
    {
        var host = new UsbDisk(0, "host-id", "host-serial", "Host", 1024L * 1024 * 1024 * 1024, 512, "NVMe", "GPT", true, true, false, false, "Healthy", ["Online"], []);
        var usb = new UsbDisk(2, "usb-id", "usb-serial", "USB", 16L * 1024 * 1024 * 1024, 512, "USB", "GPT", false, false, false, false, "Healthy", ["Online"],
            [new UsbPartition(1, "partition-id", 1048576, 10L * 1024 * 1024 * 1024, "Basic", false, false, [@"\\?\Volume{00000000-0000-0000-0000-000000000001}\"])]);
        var inventory = new UsbInventory(1, 0, [host, usb]); const long bytes = 8L * 1024 * 1024 * 1024; var count = 0;
        void Reject(UsbDisk candidate, UsbInventory? snapshot = null) { if (UsbMediaPlanning.Rejection(candidate, snapshot ?? (inventory with { Disks = [host, candidate] }), bytes).Length == 0) throw new IOException("Unsafe USB planning accepted"); count++; }
        void Deny(Action action) { try { action(); } catch (IOException) { count++; return; } catch (JsonException) { count++; return; } throw new IOException("Expected fresh USB refusal"); }
        if (!UsbMediaPlanning.Choices(inventory, bytes).Single().Eligible) throw new IOException("Valid USB planning failed"); count++;
        Reject(usb with { IsBoot = true }); Reject(usb with { IsSystem = true }); Reject(usb with { IsReadOnly = true }); Reject(usb with { IsOffline = true });
        Reject(usb with { SectorSize = 4096 }); Reject(usb with { Size = 1024 }); Reject(usb with { Serial = "" }); Reject(usb with { UniqueId = "" });
        Reject(usb with { Health = "Unknown" }); Reject(usb with { Operational = [] }); Reject(usb with { Bus = "SATA" });
        Reject(usb, inventory with { SourceDiskNumber = 2 }); Reject(usb, inventory with { Disks = [host, usb, usb with { Number = 3 }] });
        Reject(usb with { Partitions = [usb.Partitions[0] with { IsSystem = true }] });
        Reject(usb with { Partitions = [usb.Partitions[0] with { Size = usb.Size }] });
        var moved = usb with { Number = 7 };
        if (UsbMediaPlanning.Rebind(usb, inventory with { Disks = [host, moved] }, bytes).Number != 7) throw new IOException("Disk-number change should rebind by actual identity"); count++;
        Deny(() => UsbMediaPlanning.Rebind(usb, inventory with { Disks = [host, usb with { Serial = "replacement" }] }, bytes));
        Deny(() => UsbMediaPlanning.Rebind(usb, inventory with { Disks = [host, usb with { Size = usb.Size + 512 }] }, bytes));
        Deny(() => UsbMediaPlanning.Rebind(usb, inventory with { Disks = [host, usb with { Partitions = [usb.Partitions[0] with { Offset = 2097152 }] }] }, bytes));
        Deny(() => UsbMediaPlanning.Rebind(usb, inventory with { Disks = [host, usb with { IsBoot = true }] }, bytes));
        var json = JsonSerializer.Serialize(inventory);
        Deny(() => UsbMediaPlanning.Parse(json.Replace("\"IsBoot\":false,", "")));
        Deny(() => UsbMediaPlanning.Parse(JsonSerializer.Serialize(inventory with { SourceDiskNumber = 8 })));
        return JsonSerializer.Serialize(new { passed = true, checks = count, scope = "USB planning eligibility, source/boot/system exclusion, duplicate/missing hardware IDs, fresh replacement/layout refusal and number-independent rebind. Synthetic planning only; no device write authorization." });
    }
}
