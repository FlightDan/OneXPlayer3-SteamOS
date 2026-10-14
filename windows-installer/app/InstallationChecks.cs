using System.IO;
using System.Text.Json;
namespace OxpInstaller;
public static class InstallationChecks
{
    public static async Task<string> RunAsync(string prepared)
    {
        using var source = new PreparedDiskImage(prepared); var events = new List<string>();
        void Require(bool condition, string name) { if (!condition) throw new IOException(name); events.Add(name); }
        var before = Directory.GetDirectories(InstallationController.Work, "install-session-*").Length;
        try { await InstallationController.RunAsync(new(InstallationTargetKind.InternalShared, prepared, true), _ => { }, _ => { }, new CancellationToken(true)); throw new IOException("Pre-cancel accepted"); }
        catch (OperationCanceledException) { }
        Require(Directory.GetDirectories(InstallationController.Work, "install-session-*").Length == before, "pre-cancel-creates-no-session-or-target");
        try { InstallationController.ValidateRequest(new((InstallationTargetKind)99, prepared, true)); throw new InvalidOperationException("Unknown kind accepted"); }
        catch (IOException) { events.Add("unknown-installation-kind-refused"); }
        foreach (var scenario in new[] { "physical-scope", "changed-source", "cancel-before-target", "wrong-nonce", "new-with-recovery", "resume-missing-state", "resume-outside-work" })
        {
            var nonce = Guid.NewGuid().ToString("N"); var directory = Path.Combine(InstallationController.Work, "partition-deploy-" + nonce); Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "partition-job.json");
            var job = new PartitionJob(1, scenario == "wrong-nonce" ? Guid.NewGuid().ToString("N") : nonce,
                scenario == "physical-scope" ? "physical-disk" : scenario.StartsWith("resume-") ? "resume-owned-vhd-only" : "new-virtual-disk-only", InstallationTargetKind.ExternalDisk,
                scenario == "changed-source" ? source.Identity with { WriteTime = source.Identity.WriteTime + 1 } : source.Identity,
                scenario == "new-with-recovery" ? Path.Combine(directory, "state.json") : scenario == "resume-outside-work" ? Path.Combine(Backend.Root, "state.json") : null);
            await File.WriteAllTextAsync(path, JsonSerializer.Serialize(job));
            using var signal = new EventWaitHandle(scenario == "cancel-before-target", EventResetMode.ManualReset, InstallationController.EventName(nonce));
            if (scenario is "physical-scope" or "wrong-nonce" or "new-with-recovery" or "resume-missing-state" or "resume-outside-work")
            {
                var refused = false; try { await InstallationController.ExecuteHelperAsync(path); } catch (IOException) { refused = true; }
                Require(refused && !File.Exists(Path.Combine(directory, "helper.jsonl")), scenario + "-refused-before-output");
            }
            else
            {
                var exit = await InstallationController.ExecuteHelperAsync(path);
                var result = JsonSerializer.Deserialize<PartitionJobResult>(await File.ReadAllTextAsync(Path.Combine(directory, "helper-result.json")))!;
                Require(exit == (scenario == "cancel-before-target" ? 2 : 1) && result.Status == (scenario == "cancel-before-target" ? "cancelled" : "failed"), scenario + "-explicit-terminal-status");
                var original = await File.ReadAllTextAsync(Path.Combine(directory, "helper-result.json"));
                var refused = false; try { await InstallationController.ExecuteHelperAsync(path); } catch (IOException) { refused = true; }
                Require(refused && await File.ReadAllTextAsync(Path.Combine(directory, "helper-result.json")) == original, scenario + "-replay-refused-result-preserved");
            }
            Require(!File.Exists(Path.Combine(directory, "media.vhd")), scenario + "-no-created-target");
        }
        var linkDirectory = Path.Combine(InstallationController.Work, "install-path-check-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(linkDirectory);
        var sentinel = Path.Combine(linkDirectory, "original.txt"); await File.WriteAllTextAsync(sentinel, "preserve me");
        var link = Path.Combine(linkDirectory, "state.json.tmp"); File.CreateSymbolicLink(link, sentinel);
        var linkRefused = false; try { MediaSource.Ordinary(link, InstallationController.Work, false); } catch (IOException) { linkRefused = true; }
        Require(linkRefused && await File.ReadAllTextAsync(sentinel) == "preserve me", "existing-redirected-output-leaf-refused-sentinel-preserved");
        var report = Path.Combine(Backend.Root, "logs", "installation-controller-checks.json");
        await File.WriteAllTextAsync(report, JsonSerializer.Serialize(new { passed = true, events,
            scope = "Actual helper validation and cancellation event before native target creation; UI/full subprocess success is recorded separately. No physical disks or interactive normal-user UAC tested." }, new JsonSerializerOptions { WriteIndented = true }));
        return report;
    }
}

