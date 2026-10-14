using System.IO;
using System.IO.Compression;
using System.Text;

namespace OxpInstaller;

internal static class DiagnosticLogExportChecks
{
    internal static IEnumerable<string> Run(string proofDirectory)
    {
        var id = Guid.NewGuid().ToString("N");
        var directory = Path.Combine(InstallationController.Work, "install-session-" + id);
        var deployment = Path.Combine(InstallationController.Work, "partition-deploy-" + id);
        Directory.CreateDirectory(directory); Directory.CreateDirectory(deployment);
        var state = new InstallationSession(1, id, InstallationTargetKind.ExternalDisk, "fixture.img", false,
            "running", "writing", null, null, DateTime.UtcNow);
        InstallationController.Save(Path.Combine(directory, "session.json"), state with { Deployment = deployment });
        File.WriteAllText(Path.Combine(deployment, "helper.jsonl"), "{\"fixture\":true}");
        File.WriteAllText(Path.Combine(deployment, "physical-state.json"), "{\"status\":\"writing\"}");
        File.WriteAllText(Path.Combine(directory, "prepared.img"), "image fixture must not be exported");
        var fullLog = "FIRST-LINE\n" + new string('x', 90000) + "\n最后一行 / LAST-LINE\n";
        using var live = new StreamWriter(new FileStream(Path.Combine(directory, "ui.log"), FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false)) { AutoFlush = true };
        live.Write(fullLog);
        File.WriteAllText(Path.Combine(directory, "ui-resume-fixture.log"), "resumed task");
        File.WriteAllText(Path.Combine(directory, "progress.jsonl"), "{\"Step\":\"04.42\",\"Percent\":86.2}");
        var path = Path.Combine(proofDirectory, "diagnostic-export.zip");
        DiagnosticLogExport.Write(path, state, "only the visible tail");
        using (var archive = ZipFile.OpenRead(path))
        {
            string Read(string name) { using var reader = new StreamReader(archive.GetEntry(name)?.Open() ?? throw new IOException("Missing " + name)); return reader.ReadToEnd(); }
            void Require(bool value, string name) { if (!value) throw new IOException(name); }
            Require(Read("session/ui.log") == fullLog, "export-retains-full-live-log-and-utf8");
            Require(Read("session/ui-resume-fixture.log") == "resumed task", "export-includes-resumed-log");
            Require(Read("session/progress.jsonl").Contains("04.42"), "export-includes-fixed-step-progress-log");
            Require(Read("deployment/helper.jsonl").Contains("fixture") && Read("deployment/physical-state.json").Contains("writing"), "export-reads-latest-deployment-records");
            Require(!archive.Entries.Any(entry => entry.Name.EndsWith(".img")), "export-excludes-disk-images");
            Require(Read("displayed-log.txt") == "only the visible tail" && Read("export-info.json").Contains(ReleaseInfo.DisplayVersion), "export-includes-ui-snapshot-and-version");
        }
        // An early failure can be reported even before a session directory exists.
        DiagnosticLogExport.Write(path, null, "startup failure / 启动失败");
        using (var archive = ZipFile.OpenRead(path))
        using (var reader = new StreamReader(archive.GetEntry("displayed-log.txt")!.Open()))
            if (reader.ReadToEnd() != "startup failure / 启动失败") throw new IOException("early-failure-export");
        return new[] { "export-retains-full-live-log-and-utf8", "export-includes-resumed-log", "export-includes-fixed-step-progress-log", "export-reads-latest-deployment-records",
            "export-excludes-disk-images", "export-includes-ui-snapshot-and-version", "export-works-before-session-and-replaces-existing-archive" };
    }
}
