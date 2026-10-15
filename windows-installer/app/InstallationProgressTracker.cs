using System.Text.Json;

namespace OxpInstaller;

// Calibrated from the retained 2026-10-14 capacity run. Percent is overall
// completed work, not elapsed time. Unknown-duration operations advance only
// at confirmed milestones; downloads have their own byte-based progress.
internal sealed class InstallationProgressTracker
{
    private readonly Dictionary<string, (long Size, long Written, long Verified)> partitions = new();
    private readonly HashSet<string> components = new();
    private readonly HashSet<string> verifiedSlots = new();
    private string pending = "";
    internal double Percent { get; private set; }
    internal string ComponentStep { get; private set; } = "02.01";
    internal string ComponentDetail { get; private set; } = "";
    internal static string PartitionStep(string role, string operation)
    {
        var index = Array.IndexOf(PreparedDisk.Roles, role);
        return index < 0 ? "04.00" : $"04.{index + 1}{(operation == "verifying" ? 2 : 1)}";
    }

    internal double Advance(string stage, double fraction)
    {
        if (!double.IsFinite(fraction) || fraction < 0 || fraction > 1) return Percent;
        var (start, weight) = stage switch
        {
            "preparing" => (0d, 32d), "components" => (32d, 43d),
            "bootloader" => (75d, 3d), "writing" => (78d, 22d),
            _ => (Percent, 0d)
        };
        Percent = Math.Max(Percent, Math.Min(99, start + weight * fraction));
        return Percent;
    }

    internal void SetPartitions(IEnumerable<(string Name, long Size)> layout)
    {
        partitions.Clear();
        foreach (var (name, size) in layout)
            if (size > 0) partitions.Add(name, (size, 0, 0));
    }

    internal bool ObservePartition(string line)
    {
        if (line.StartsWith("PARTITION_PROGRESS=", StringComparison.Ordinal))
        {
            var fields = line[19..].Split(':');
            if (fields.Length != 5 || !partitions.TryGetValue(fields[0], out var part)
                || fields[1] is not ("writing" or "verifying")
                || !long.TryParse(fields[2], out var written) || !long.TryParse(fields[3], out var verified)
                || !long.TryParse(fields[4], out var size) || size != part.Size
                || written < 0 || verified < 0 || written > size || verified > size) return false;
            partitions[fields[0]] = (size, Math.Max(part.Written, written), Math.Max(part.Verified, verified));
        }
        else
        {
            var prefix = line.StartsWith("PARTITION_DEPLOYED=", StringComparison.Ordinal) ? "PARTITION_DEPLOYED="
                : line.StartsWith("PARTITION_RECHECKED=", StringComparison.Ordinal) ? "PARTITION_RECHECKED=" : null;
            if (prefix == null || !partitions.TryGetValue(line[prefix.Length..], out var part)) return false;
            partitions[line[prefix.Length..]] = (part.Size, part.Size, part.Size);
        }
        var total = partitions.Values.Sum(p => 2d * p.Size);
        if (total > 0) Advance("writing", partitions.Values.Sum(p => (double)p.Written + p.Verified) / total);
        return true;
    }

    // Guest console output arrives in arbitrary chunks, sometimes splitting JSON.
    // Deduplicate A/B records and retain only bounded, complete console lines.
    internal bool ObserveComponents(string chunk, int expectedRecords, bool verify)
    {
        var changed = false;
        pending += chunk;
        var lines = pending.Split('\n'); pending = lines[^1];
        if (pending.Length > 65536) pending = pending[^65536..];
        foreach (var line in lines[..^1])
        {
            const string result = "OXP_COMPONENT_RESULT=";
            const string check = "OXP_INTEGRATION_VERIFY=";
            var marker = line.IndexOf(result, StringComparison.Ordinal);
            var checking = false;
            if (marker < 0) { marker = line.IndexOf(check, StringComparison.Ordinal); checking = true; }
            if (marker < 0) continue;
            try
            {
                using var json = JsonDocument.Parse(line[(marker + (checking ? check.Length : result.Length))..].Trim());
                var item = json.RootElement;
                var slot = item.GetProperty("slot").GetString();
                if (slot is not ("A" or "B")) continue;
                if (checking)
                {
                    if (verify && item.GetProperty("readonly").GetBoolean())
                    { changed |= verifiedSlots.Add(slot); ComponentStep = slot == "A" ? "02.03" : "02.04"; ComponentDetail = slot; }
                }
                else
                {
                    var id = item.GetProperty("id").GetString();
                    changed |= components.Add(slot + ":" + id);
                    ComponentStep = slot == "A" ? "02.01" : "02.02";
                    ComponentDetail = slot + " / " + (id == "system-update-hold"
                        ? PartitionInventory.L("保留当前系统版本", "Preserve current system version") : id);
                }
            }
            catch (Exception error) when (error is JsonException or KeyNotFoundException or InvalidOperationException) { }
        }
        if (changed)
        {
            var installed = expectedRecords > 0 ? Math.Min(1d, components.Count / (double)expectedRecords) : 0;
            // 88% of component work is installation, 12% is independent verification.
            Advance("components", verify ? .88 * installed + .12 * verifiedSlots.Count / 2d : installed);
        }
        return changed;
    }

    internal double Complete() => Percent = 100;
}
