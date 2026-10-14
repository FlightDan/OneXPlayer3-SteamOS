using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class ReviewedInstallationCli
{
    // CLI counterpart of the final wizard action. Uses the same validation,
    // journal, administrator helper, disk binding and bounded writes as the UI.
    internal static async Task<string> RunAsync(string requestPath)
    {
        requestPath = Path.GetFullPath(requestPath);
        if (new FileInfo(requestPath).Length > 65536) throw new IOException("Installation request is too large.");
        var request = JsonSerializer.Deserialize<InstallationRequest>(await File.ReadAllTextAsync(requestPath))
            ?? throw new IOException("Missing installation request.");
        if (!request.Physical || request.PlannedPartition == null || request.PlannedPartition.Example)
            throw new IOException("Expected an explicitly reviewed physical installation request.");
        InstallationController.ValidateRequest(request);
        var path = Path.Combine(InstallationController.Work, "reviewed-install-" + Guid.NewGuid().ToString("N") + ".log");
        using var writer = new StreamWriter(new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
        void Log(string text) { lock (writer) writer.WriteLine(text); }
        var state = await InstallationController.RunAsync(request,
            progress => Log(JsonSerializer.Serialize(progress)), Log, CancellationToken.None,
            created => Log("INSTALL_SESSION=" + InstallationController.SessionDirectory(created)));
        Log("INSTALL_STATUS=" + state.Status);
        if (state.Status != "awaiting-device-boot") throw new IOException(state.Error ?? "Installation did not finish: " + state.Status);
        return InstallationController.SessionDirectory(state);
    }
}
