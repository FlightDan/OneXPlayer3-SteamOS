using System.Text.Json;
namespace OxpInstaller;
public static class PlanningChecks
{
    public static object HandoffFixture()
    {
        const long GiB = 1024L * 1024 * 1024;
        const string diskGuid = "11111111-1111-1111-1111-111111111111";
        var parts = new[] {
            new { number = 1, guid = "22222222-2222-2222-2222-222222222222", offset = 1024L * 1024, size = 64L * 1024 * 1024, gptType = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B", name = "Windows EFI fixture" },
            new { number = 4, guid = "33333333-3333-3333-3333-333333333333", offset = 65L * 1024 * 1024, size = 10 * GiB, gptType = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7", name = "Windows data fixture" }
        };
        var windows = JsonSerializer.Serialize(new[] { new { number = 0, guid = diskGuid, sectorSize = 512, model = "Windows display fixture", size = 80 * GiB, style = "GPT", bus = "NVMe", partitions = parts } });
        var target = DiskPlanning.FreeSpaces(windows).Single();
        return new { scope = "Synthetic cross-language metadata fixture; not a Windows operating system or physical installation", selection = DiskPlanning.Preview(target), candidates = new[] {
            new { size = 80 * GiB, sector_size = 512, table = new { device = "/dev/nvme7n1", id = diskGuid, label = "gpt", sectorsize = 512, firstlba = 2048, lastlba = 80 * GiB / 512 - 34,
                partitions = parts.Select(p => new { node = "/dev/nvme7n1p" + p.number, start = p.offset / 512, size = p.size / 512, uuid = p.guid, type = p.gptType, name = p.name }) } }
        } };
    }
    public static string Run()
    {
        const long GiB = 1024L * 1024 * 1024;
        string Layout(string style, string bus, params (long offset, long size)[] partitions) => JsonSerializer.Serialize(new[] { new { number = 1, guid = "11111111-1111-1111-1111-111111111111", sectorSize = 512, model = "fixture", size = 256 * GiB, style, bus,
            partitions = partitions.Select((p, index) => new { number = index + 1, guid = "00000000-0000-0000-0000-" + (index + 1).ToString("D12"), gptType = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7", p.offset, p.size }) } });
        static void Require(bool condition, string name) { if (!condition) throw new Exception("Planning check failed: " + name); }
        var windows = (offset: 1024L * 1024, size: 100 * GiB);
        var recovery = (offset: 200 * GiB, size: 2 * GiB);
        var gaps = DiskPlanning.FreeSpaces(Layout("GPT", "NVMe", windows, recovery));
        Require(gaps.Count == 1, "only the middle gap qualifies; small tail is excluded");
        var gap = gaps.Single();
        Require(gap.Identity != null && gap.Identity.Partitions.Length == 2, "handoff contains disk and all original partition identities");
        Require(DiskPlanning.FreeSpaces("[{\"number\":1,\"model\":\"unknown\",\"size\":274877906944,\"style\":\"GPT\",\"bus\":\"NVMe\",\"partitions\":[]}]").Count == 0, "missing identity does not yield a selectable gap");
        Require(gap.Start >= windows.offset + windows.size && gap.Start + gap.Size <= recovery.offset, "existing partitions preserved");
        var parts = JsonSerializer.SerializeToElement(DiskPlanning.Layout(gap)).EnumerateArray().ToArray();
        Require(parts.Length == 8 && parts[0].GetProperty("start").GetInt64() == gap.Start, "dual-slot layout starts within gap");
        for (var i = 1; i < parts.Length; i++) Require(parts[i].GetProperty("start").GetInt64() == parts[i-1].GetProperty("start").GetInt64() + parts[i-1].GetProperty("size").GetInt64(), "contiguous nonoverlapping parts");
        Require(parts[^1].GetProperty("start").GetInt64() + parts[^1].GetProperty("size").GetInt64() == gap.Start + gap.Size, "end stays within selected gap");
        Require(DiskPlanning.FreeSpaces(Layout("MBR", "NVMe")).Count == 0 && DiskPlanning.FreeSpaces(Layout("GPT", "Spaces")).Count == 0, "unsupported layouts excluded");
        var rejected = false;
        try { DiskPlanning.FreeSpaces(Layout("GPT", "NVMe", (GiB, 100 * GiB), (50 * GiB, 20 * GiB))); } catch (InvalidOperationException) { rejected = true; }
        Require(rejected, "overlapping metadata rejected");
        rejected = false;
        try { DiskPlanning.Layout(new(1, "fixture", 256 * GiB, GiB, 32 * GiB)); } catch (InvalidOperationException) { rejected = true; }
        Require(rejected, "insufficient space rejected");
        return "Space planner: gap bounds, preserved partitions, dual slots, overlap rejection, unsupported layouts and insufficient space passed.";
    }
}
