using System.IO;
using System.Text.Json;

namespace OxpInstaller;

// Runs the production controller against newly created, tool-owned virtual disks.
internal static class FullVirtualWorkflowChecks
{
    internal static async Task<string> RunAsync(string recovery)
    {
        InstallerI18n.SetLanguage("zh-CN");
        var directory = Path.Combine(InstallationController.Work, "full-virtual-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var resultPath = Path.Combine(directory, "result.json");
        using var writer = new StreamWriter(Path.Combine(directory, "workflow.log")) { AutoFlush = true };
        void Log(string text) { lock (writer) writer.WriteLine(text); }
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(45));
        var checks = new List<string>();
        void Require(bool condition, string label) { if (!condition) throw new IOException(label); checks.Add(label); Log("CHECK=" + label); }
        try
        {
            await OfficialSystem.StageBundleAsync(Log, timeout.Token, fresh: true);
            Require(OfficialSystem.IsBundleReady(), "official-raucb-staged-before-installation");
            var options = InstallerOptions.Defaults;
            var internalSession = await InstallationController.RunAsync(new(InstallationTargetKind.InternalShared,
                recovery, false, options, Physical: false, UpgradeTo310: true, Refind: new("SteamOS", 1)),
                p => Log(JsonSerializer.Serialize(p)), Log, timeout.Token,
                s => Log("INTERNAL_SESSION=" + InstallationController.SessionDirectory(s)));
            Require(internalSession.Status == "complete", "internal-controller-complete: " + internalSession.Error);
            var internalDirectory = InstallationController.SessionDirectory(internalSession);
            using (var components = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(internalDirectory, "components.json"))))
                Require(components.RootElement.GetArrayLength() >= 2 * (options.Repairs.Length + options.Plugins.Length)
                    && components.RootElement.EnumerateArray().All(x => x.GetProperty("status").GetString() == "files_installed"),
                    "all-default-components-installed-in-both-slots");
            var prepared = Path.Combine(internalDirectory, "prepared.img");
            var selection = JsonSerializer.Serialize(options, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
            await Backend.GuestAsync("integration-verify", prepared, false, Log, timeout.Token, selection: selection);
            Require(File.Exists(Path.Combine(internalSession.Deployment!, "boot-proof.json")), "internal-written-vhd-uefi-boot-proof");
            var externalSession = await InstallationController.RunAsync(new(InstallationTargetKind.ExternalDisk,
                prepared, true, Physical: false), p => Log(JsonSerializer.Serialize(p)), Log, timeout.Token,
                s => Log("EXTERNAL_SESSION=" + InstallationController.SessionDirectory(s)));
            Require(externalSession.Status == "complete", "external-controller-complete: " + externalSession.Error);
            Require(File.Exists(Path.Combine(externalSession.Deployment!, "boot-proof.json")), "external-written-vhd-uefi-boot-proof");
            await File.WriteAllTextAsync(resultPath, JsonSerializer.Serialize(new { passed = true, checks,
                internalSession = internalDirectory, externalSession = InstallationController.SessionDirectory(externalSession),
                internalDeployment = internalSession.Deployment, externalDeployment = externalSession.Deployment,
                scope = "Recovery import, official 3.10 preparation, default A/B components and independent verification, rEFInd, native internal/external VHD writes/readback and independent UEFI boots. No physical disk installation or real Windows boot." },
                new JsonSerializerOptions { WriteIndented = true }));
        }
        catch (Exception error)
        {
            await File.WriteAllTextAsync(resultPath, JsonSerializer.Serialize(new { passed = false, checks, error = error.ToString() }, new JsonSerializerOptions { WriteIndented = true }));
            throw;
        }
        return resultPath;
    }
}
