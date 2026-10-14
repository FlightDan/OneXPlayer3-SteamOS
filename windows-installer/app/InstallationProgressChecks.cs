using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class InstallationProgressChecks
{
    internal static string Run(string? evidenceDirectory = null)
    {
        var checks = new List<string>();
        void Require(bool value, string label) { if (!value) throw new IOException(label); checks.Add(label); }
        void Near(double actual, double expected, string label) => Require(Math.Abs(actual - expected) < .000001, label);
        var progress = new InstallationProgressTracker();
        Near(progress.Advance("preparing", 1), 32, "preparation-boundary");
        Near(progress.Advance("components", 1), 75, "components-boundary");
        Near(progress.Advance("bootloader", 1), 78, "bootloader-boundary");
        Near(progress.Advance("preparing", .5), 78, "late-capacity-preparation-cannot-regress");
        Near(progress.Advance("permission", 0), 78, "permission-pause-keeps-progress");
        progress.SetPartitions([("esp", 10), ("home", 90)]);
        Require(progress.ObservePartition("PARTITION_DEPLOYED=esp"), "small-partition-completion-is-recognized");
        Near(progress.Percent, 80.2, "partition-weighted-by-bytes-not-count");
        progress.ObservePartition("PARTITION_PROGRESS=home:writing:45:0:90");
        Near(progress.Percent, 85.15, "aggregate-write-progress-includes-completed-prefix");
        progress.ObservePartition("PARTITION_PROGRESS=home:verifying:90:45:90");
        Near(progress.Percent, 95.05, "readback-is-half-of-each-partition-work");
        progress.ObservePartition("PARTITION_PROGRESS=home:writing:1:0:90");
        Near(progress.Percent, 95.05, "stale-events-cannot-regress");
        Require(!progress.ObservePartition("PARTITION_PROGRESS=home:verifying:90:90:91")
            && !progress.ObservePartition("PARTITION_PROGRESS=home:verifying:90:91:90")
            && !progress.ObservePartition("PARTITION_PROGRESS=unknown:writing:1:0:90"), "reject-mismatched-range-invalid-count-unknown-role");
        Near(progress.Advance("writing", double.NaN), 95.05, "ignore-nonfinite-fraction");
        progress.ObservePartition("PARTITION_DEPLOYED=home");
        Near(progress.Percent, 99, "full-byte-comparison-still-awaits-backend-success");
        Near(progress.Advance("failed", 0), 99, "failure-retains-last-percent");
        Near(progress.Advance("cancelled", 0), 99, "cancellation-retains-last-percent");
        Near(progress.Complete(), 100, "only-explicit-success-reaches-100");

        var skipped = new InstallationProgressTracker();
        Near(skipped.Advance("bootloader", 1), 78, "prepared-and-unselected-stages-credit-without-renormalizing");
        skipped.SetPartitions([("esp", 10), ("home", 90)]);
        skipped.ObservePartition("PARTITION_RECHECKED=esp");
        Near(skipped.Percent, 80.2, "resume-credits-only-rechecked-prefix");
        Require(!skipped.ObservePartition("PARTITION_RECHECKING=home"), "starting-recheck-does-not-credit-unverified-bytes");
        foreach (var (role, index) in PreparedDisk.Roles.Select((role, index) => (role, index + 1)))
        {
            Require(InstallationProgressTracker.PartitionStep(role, "writing") == $"04.{index}1"
                && InstallationProgressTracker.PartitionStep(role, "verifying") == $"04.{index}2", "stable-write-readback-codes-" + role);
        }

        var components = new InstallationProgressTracker();
        components.Advance("preparing", 1);
        Require(!components.ObserveComponents("OXP_COMPONENT_RES", 4, true), "split-console-marker-waits-for-complete-line");
        Require(components.ObserveComponents("ULT={\"slot\":\"A\",\"id\":\"wifi\"}\n", 4, true), "split-console-json-parses-once");
        Near(components.Percent, 41.46, "component-install-reserves-independent-verification");
        Require(!components.ObserveComponents("OXP_COMPONENT_RESULT={\"slot\":\"A\",\"id\":\"wifi\"}\n", 4, true), "duplicate-component-does-not-inflate-progress");
        components.ObserveComponents("OXP_COMPONENT_RESULT={\"slot\":\"A\",\"id\":\"input\"}\nOXP_COMPONENT_RESULT={\"slot\":\"B\",\"id\":\"wifi\"}\nOXP_COMPONENT_RESULT={\"slot\":\"B\",\"id\":\"input\"}\n", 4, true);
        Near(components.Percent, 69.84, "both-slot-installs-stop-short-of-verified-boundary");
        Require(components.ComponentStep == "02.02" && components.ComponentDetail == "B / input", "component-code-and-id-identify-slot");
        components.ObserveComponents("OXP_INTEGRATION_VERIFY={\"slot\":\"A\",\"readonly\":true}\n", 4, true);
        Near(components.Percent, 72.42, "slot-A-independent-verification");
        components.ObserveComponents("OXP_INTEGRATION_VERIFY={\"slot\":\"B\",\"readonly\":true}\n", 4, true);
        Near(components.Percent, 75, "slot-B-independent-verification");
        Require(components.ComponentStep == "02.04", "readonly-verification-has-distinct-code");
        var empty = new InstallationProgressTracker();
        Require(!empty.ObserveComponents("OXP_COMPONENT_RESULT=broken\n", 0, true), "malformed-console-record-does-not-break-installation");
        Near(empty.Advance("components", 1), 75, "empty-selection-completes-on-success");

        object? replay = null;
        if (evidenceDirectory != null)
        {
            var layout = JsonSerializer.Deserialize<PreparedDisk>(File.ReadAllText(Path.Combine(evidenceDirectory, "partition-layout.json")))!;
            var recorded = new InstallationProgressTracker(); recorded.Advance("bootloader", 1);
            recorded.SetPartitions(layout.System.Select(p => (p.Name, p.Size)));
            var events = 0; var previous = recorded.Percent; var completed = new HashSet<string>();
            foreach (var line in File.ReadLines(Path.Combine(evidenceDirectory, "full-transcript.log")))
            {
                if (!recorded.ObservePartition(line)) continue;
                events++;
                Require(recorded.Percent >= previous && recorded.Percent < 100, "retained-native-event-monotonic-" + events);
                previous = recorded.Percent;
                if (line.StartsWith("PARTITION_DEPLOYED=")) completed.Add(line[19..]);
            }
            Require(events > 8 && completed.SetEquals(PreparedDisk.Roles), "real-native-log-replays-all-eight-partitions");
            Near(recorded.Percent, 99, "real-native-log-awaits-final-success");
            replay = new { evidenceDirectory, events, completed = completed.Count, percent = recorded.Percent };
        }
        return JsonSerializer.Serialize(new { passed = true, checks, replay }, new JsonSerializerOptions { WriteIndented = true });
    }
}
