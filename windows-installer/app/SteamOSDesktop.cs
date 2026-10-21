using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OxpInstaller;

internal sealed record DesktopRebootResult(string? Path, string? Warning);

internal static class SteamOSDesktop
{
    internal static string Build(InstallationTargetKind kind, string deployment)
    {
        var name = ""; var entry = "";
        if (kind == InstallationTargetKind.InternalShared)
        {
            using var result = JsonDocument.Parse(File.ReadAllText(Path.Combine(deployment, "firmware-result.json")));
            using var backup = JsonDocument.Parse(File.ReadAllText(Path.Combine(deployment, "firmware-before.json")));
            name = result.RootElement.GetProperty("name").GetString() ?? "";
            if (result.RootElement.GetProperty("status").GetString() != "registered"
                || !Regex.IsMatch(name, "^Boot[0-9A-F]{4}$")
                || backup.RootElement.GetProperty("name").GetString() != name)
                throw new IOException("SteamOS firmware registration is missing or inconsistent.");
            entry = backup.RootElement.GetProperty("entry").GetString() ?? "";
            var bytes = Convert.FromBase64String(entry);
            if (bytes.Length < 8 || (bytes[0] & 1) == 0) throw new IOException("Invalid SteamOS firmware entry.");
            entry = Convert.ToBase64String(bytes);
        }
        else if (kind != InstallationTargetKind.ExternalDisk) throw new IOException("Unsupported installation target.");
        using var stream = typeof(SteamOSDesktop).Assembly.GetManifestResourceStream("OxpInstaller.RestartToSteamOS.bat")!;
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd().Replace("@@BOOT_NAME@@", name).Replace("@@BOOT_ENTRY@@", entry)
            .Replace("\r\n", "\n").Replace("\n", "\r\n");
    }

    internal static string Write(string desktop, string content, string language = "zh-CN")
    {
        if (string.IsNullOrWhiteSpace(desktop) || !Directory.Exists(desktop)) throw new IOException("Windows desktop folder is unavailable.");
        var name = language == "en-US" ? "Restart to SteamOS" : "重启到 SteamOS";
        return WriteUnused(desktop, name, content);
    }

    // The persistent core contains the whole firmware transaction and native wrapper.
    // Content-addressed names keep repeat installations idempotent without replacing edits.
    internal static string PersistCore(string programDirectory, string content)
    {
        if (string.IsNullOrWhiteSpace(programDirectory)) throw new IOException("Windows Program Files folder is unavailable.");
        CreateSafeDirectory(Path.GetFullPath(programDirectory));
        var digest = Convert.ToHexString(SHA256.HashData(new UTF8Encoding(false).GetBytes(content))).ToLowerInvariant();
        return WriteUnused(programDirectory, "RestartToSteamOS-" + digest, content, protectedPath: true);
    }

    internal static string BuildLauncher(string corePath)
    {
        var path64 = Convert.ToBase64String(Encoding.Unicode.GetBytes(Path.GetFullPath(corePath)));
        // Only base64 data reaches CMD. Neither CMD nor PowerShell interprets path characters.
        var command = "$ErrorActionPreference='Stop'; try { "
            + "$env:OXP3_STEAMOS_BAT=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + path64 + "')); "
            + "$item=Get-Item -LiteralPath $env:OXP3_STEAMOS_BAT -Force; "
            + "while($null -ne $item) { if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unsafe restart script path.' }; "
            + "if($item -is [IO.FileInfo]) { $item=$item.Directory } else { $item=$item.Parent } }; "
            + "& ([scriptblock]::Create(([regex]::Split([IO.File]::ReadAllText($env:OXP3_STEAMOS_BAT), '(?m)^# OXP3-POWERSHELL\\r?$'))[1])) "
            + "} catch { Write-Host $_; exit 1 }";
        var encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(command));
        return "@echo off\r\nsetlocal DisableDelayedExpansion\r\n"
            + "\"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -NoProfile -EncodedCommand " + encoded + "\r\n"
            + "set \"OXP3_EXIT=%errorlevel%\"\r\nif not \"%OXP3_EXIT%\"==\"0\" pause\r\nexit /b %OXP3_EXIT%\r\n";
    }

    private static void RejectReparsePoints(string path)
    {
        for (var current = Path.GetFullPath(path); current is not null; current = Path.GetDirectoryName(current))
        {
            try
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Restart script path contains a reparse point: " + current);
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
        }
    }

    private static void CreateSafeDirectory(string directory)
    {
        RejectReparsePoints(directory);
        if (!Directory.Exists(directory))
        {
            var parent = Path.GetDirectoryName(directory) ?? throw new IOException("Invalid restart script directory.");
            CreateSafeDirectory(parent);
            Directory.CreateDirectory(directory);
        }
        RejectReparsePoints(directory);
    }

    private static string WriteUnused(string directory, string name, string content, bool protectedPath = false)
    {
        for (var index = 1; index <= 100; index++)
        {
            var path = Path.Combine(directory, index == 1 ? name + ".bat" : $"{name} ({index}).bat");
            if (protectedPath) RejectReparsePoints(path);
            if (File.Exists(path))
            {
                if (File.ReadAllText(path) == content) return path;
                continue; // Preserve existing or edited user files.
            }
            var temporary = Path.Combine(directory, ".oxp3-reboot-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false))) writer.Write(content);
                if (protectedPath) RejectReparsePoints(path);
                File.Move(temporary, path, false);
                return path;
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        throw new IOException("No unused restart script filename is available.");
    }

    internal static DesktopRebootResult Install(InstallationTargetKind kind, string deployment, Action<string> log, string language)
    {
        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        return InstallAt(kind, deployment, Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
            string.IsNullOrWhiteSpace(programFiles) ? "" : Path.Combine(programFiles, "OXP3 SteamOS", "Boot"), log, language);
    }

    // Explicit paths keep validation isolated from the real desktop and Program Files.
    internal static DesktopRebootResult InstallAt(InstallationTargetKind kind, string deployment, string desktop,
        string programDirectory, Action<string> log, string language)
    {
        try
        {
            var core = PersistCore(programDirectory, Build(kind, deployment));
            var path = Write(desktop, BuildLauncher(core), language);
            log("PERSISTENT_STEAMOS_SCRIPT=" + core);
            log("DESKTOP_STEAMOS_SCRIPT=" + path);
            return new(path, null);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException
            or KeyNotFoundException or InvalidOperationException or FormatException or ArgumentException)
        {
            log("DESKTOP_STEAMOS_SCRIPT_WARNING=" + error.Message);
            return new(null, error.Message); // Successful disk installation remains successful.
        }
    }
}
