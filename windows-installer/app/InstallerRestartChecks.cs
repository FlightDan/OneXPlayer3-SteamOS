using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class InstallerRestartChecks
{
    internal static async Task<string> RunAsync()
    {
        var directory = Path.Combine(InstallationController.Work, "restart-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Require(bool value, string name) { if (!value) throw new IOException(name); checks.Add(name); }
        foreach (var defaultBoot in new[] { false, true })
        {
            var start = InstallerRestart.StartInfo(defaultBoot);
            Require(start.FileName == Path.Combine(Environment.SystemDirectory, "shutdown.exe")
                && start.Arguments == (defaultBoot ? "/r /t 0" : "/r /fw /t 0"), "target-and-boot-mode-" + defaultBoot);
            Require(!start.UseShellExecute && start.Verb == "" && start.CreateNoWindow
                && start.RedirectStandardOutput && start.RedirectStandardError, "direct-process-and-capture-" + defaultBoot);
        }
        foreach (var exit in new[] { 0, 87 })
        {
            var path = Path.Combine(directory, $"exit-{exit}.jsonl");
            var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "WindowsPowerShell/v1.0/powershell.exe"))
            { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var argument in new[] { "-NoProfile", "-NonInteractive", "-Command",
                "if (!(Test-Path -LiteralPath '" + path.Replace("'", "''") + "')) { exit 99 }; "
                + "[Console]::Out.WriteLine('restart-check-out'); [Console]::Error.WriteLine('restart-check-error'); exit " + exit })
                start.ArgumentList.Add(argument);
            Exception? failure = null;
            try { await InstallerRestart.RunAsync(start, path); } catch (IOException error) { failure = error; }
            Require(exit == 0 ? failure == null : failure?.Message.Contains("87 / 0x00000057") == true
                && failure.Message.Contains("restart-check-error") && failure.Message.Contains("restart-check-out"), "exit-outcome-" + exit);
            var records = File.ReadAllLines(path).Select(line => JsonSerializer.Deserialize<JsonElement>(line)).ToArray();
            Require(records[0].GetProperty("stage").GetString() == "prepared"
                && records.Count(x => x.GetProperty("stage").GetString() == "started") == 1, "prepared-before-single-launch-" + exit);
            var result = records.Single(x => x.GetProperty("stage").GetString() == "exited");
            Require(result.GetProperty("exitCode").GetInt32() == exit
                && result.GetProperty("stdout").GetString()!.Contains("restart-check-out")
                && result.GetProperty("stderr").GetString()!.Contains("restart-check-error"), "separate-streams-and-code-persisted-" + exit);
        }
        var missingLog = Path.Combine(directory, "missing.jsonl");
        try
        {
            await InstallerRestart.RunAsync(new ProcessStartInfo(Path.Combine(directory, "missing.exe"))
            { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true }, missingLog);
            throw new IOException("Missing executable accepted.");
        }
        catch (Win32Exception error)
        {
            var result = JsonSerializer.Deserialize<JsonElement>(File.ReadAllLines(missingLog)[^1]);
            Require(result.GetProperty("stage").GetString() == "failed"
                && result.GetProperty("nativeErrorCode").GetInt32() == error.NativeErrorCode, "launch-error-persisted");
        }
        return JsonSerializer.Serialize(new { checks, directory, restartExecuted = false }, new JsonSerializerOptions { WriteIndented = true });
    }
}
