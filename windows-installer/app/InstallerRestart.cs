using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

namespace OxpInstaller;

internal static class InstallerRestart
{
    internal static ProcessStartInfo StartInfo(bool defaultBoot) => new(Path.Combine(Environment.SystemDirectory, "shutdown.exe"))
    {
        // The launcher requires administrator rights; the child inherits them.
        // Use the direct process path verified on G3E, without another shell/runas.
        Arguments = defaultBoot ? "/r /t 0" : "/r /fw /t 0",
        UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
        RedirectStandardOutput = true, RedirectStandardError = true
    };

    // Checks exercise this same runner with harmless child processes, never shutdown.
    internal static async Task RunAsync(ProcessStartInfo start, string logPath)
    {
        using var file = new FileStream(logPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        using var writer = new StreamWriter(file, new UTF8Encoding(false));
        void Record(object value)
        {
            writer.WriteLine(JsonSerializer.Serialize(value));
            writer.Flush(); file.Flush(true);
        }
        // Persist the attempt before launching: successful /t 0 may end the app
        // before any subsequent records can be saved.
        Record(new { stage = "prepared", utc = DateTime.UtcNow, host = Environment.MachineName,
            executable = start.FileName, arguments = start.Arguments });
        using var process = new Process { StartInfo = start };
        try
        {
            if (!process.Start()) throw new IOException("Could not start the restart command.");
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            Record(new { stage = "started", utc = DateTime.UtcNow, pid = process.Id });
            await process.WaitForExitAsync();
            var output = await stdout;
            var error = await stderr;
            var code = process.ExitCode;
            var hex = $"0x{code:X8}";
            Record(new { stage = "exited", utc = DateTime.UtcNow, pid = process.Id,
                exitCode = code, exitCodeHex = hex, stdout = output, stderr = error });
            if (code != 0)
                throw new IOException(PartitionInventory.L($"重启命令失败（退出码 {code} / {hex}）。", $"Restart command failed (exit code {code} / {hex}).")
                    + "\n" + (error + "\n" + output).Trim());
        }
        catch (Exception error)
        {
            Record(new { stage = "failed", utc = DateTime.UtcNow, error = error.Message,
                nativeErrorCode = error is Win32Exception native ? (int?)native.NativeErrorCode : null });
            throw;
        }
    }
}
