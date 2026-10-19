using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace OxpInstaller;

// Owned synthetic PowerShell children only; no device or installation commands.
internal static class ProcessChecks
{
    internal static async Task<string> RunAsync()
    {
        var directory = Path.Combine(Backend.Root, "work", "process-checks-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var child = Path.Combine(directory, "child.ps1");
        await File.WriteAllTextAsync(child, """
            [IO.File]::WriteAllText($args[1], [string]$PID)
            if ($args[0] -eq 'normal') { [Console]::Out.WriteLine('stdout-ok'); [Console]::Error.WriteLine('stderr-ok'); exit 0 }
            if ($args[0] -eq 'lines') { [Console]::Out.WriteLine('first'); [Console]::Out.WriteLine(); [Console]::Out.WriteLine('second'); exit 0 }
            if ($args[0] -eq 'nonzero') { exit 7 }
            while ($true) {
                if ($args[0] -eq 'stderr') { [Console]::Error.WriteLine(('x' * 4096)) }
                else { [Console]::Out.WriteLine(('x' * 4096)) }
            }
            """);
        var executable = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        string[] Arguments(string mode, string pidFile) => ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", child, mode, pidFile];
        var checks = new List<string>();
        void Require(bool value, string name) { if (!value) throw new IOException(name); checks.Add(name); }
        void Exited(string pidFile)
        {
            var pid = int.Parse(File.ReadAllText(pidFile));
            try { using var process = Process.GetProcessById(pid); Require(process.HasExited, "child-exited-" + Path.GetFileName(pidFile)); }
            catch (ArgumentException) { checks.Add("child-reaped-" + Path.GetFileName(pidFile)); }
        }
        foreach (var stream in new[] { "stdout", "stderr" })
        {
            using var safety = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            var pidFile = Path.Combine(directory, stream + ".pid");
            var failure = new IOException("Injected log write failure: " + stream);
            try
            {
                await Backend.ProcessAsync(executable, Arguments(stream, pidFile), _ => throw failure, safety.Token).WaitAsync(TimeSpan.FromSeconds(10));
                throw new IOException("Log failure was lost");
            }
            catch (IOException error) when (ReferenceEquals(error, failure)) { checks.Add(stream + "-log-failure-preserved"); }
            Exited(pidFile);
        }
        var normal = await Backend.ProcessAsync(executable, Arguments("normal", Path.Combine(directory, "normal.pid")), _ => { }, CancellationToken.None);
        Require(normal.Contains("stdout-ok") && normal.Contains("stderr-ok"), "both-streams-drained");
        var captured = new System.Text.StringBuilder();
        await Backend.ProcessAsync(executable, Arguments("lines", Path.Combine(directory, "lines.pid")),
            text => captured.Append(text), CancellationToken.None);
        Require(captured.ToString() == "first" + Environment.NewLine + Environment.NewLine + "second" + Environment.NewLine,
            "log-callback-preserves-line-and-blank-line-boundaries");
        try
        {
            await Backend.ProcessAsync(executable, Arguments("nonzero", Path.Combine(directory, "nonzero.pid")), _ => { }, CancellationToken.None);
            throw new IOException("Nonzero exit was lost");
        }
        catch (InvalidOperationException error) when (error.Message.Contains("7")) { checks.Add("nonzero-exit-preserved"); }
        using (var stop = new CancellationTokenSource(TimeSpan.FromSeconds(15)))
        {
            var pidFile = Path.Combine(directory, "cancel.pid");
            try
            {
                await Backend.ProcessAsync(executable, Arguments("stdout", pidFile), _ => stop.Cancel(), stop.Token).WaitAsync(TimeSpan.FromSeconds(10));
                throw new IOException("Cancellation was lost");
            }
            catch (OperationCanceledException) { checks.Add("user-cancellation-preserved"); }
            Exited(pidFile);
        }
        using (var stopped = new CancellationTokenSource())
        {
            stopped.Cancel();
            var pidFile = Path.Combine(directory, "pre-cancel.pid");
            try
            {
                await Backend.ProcessAsync(executable, Arguments("normal", pidFile), _ => { }, stopped.Token);
                throw new IOException("Pre-cancelled process was started");
            }
            catch (OperationCanceledException) { checks.Add("pre-cancellation-preserved"); }
            Require(!File.Exists(pidFile), "pre-cancellation-does-not-start-child");
        }
        return JsonSerializer.Serialize(new { passed = true, checks, directory, physical_disk_writes = false });
    }
}
