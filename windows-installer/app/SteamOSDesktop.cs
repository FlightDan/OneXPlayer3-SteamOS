using System.IO;
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
        for (var index = 1; index <= 100; index++)
        {
            var path = Path.Combine(desktop, index == 1 ? name + ".bat" : $"{name} ({index}).bat");
            if (File.Exists(path))
            {
                if (File.ReadAllText(path) == content) return path;
                continue; // Preserve existing or edited user files.
            }
            var temporary = Path.Combine(desktop, ".oxp3-reboot-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                File.WriteAllText(temporary, content, new UTF8Encoding(false));
                File.Move(temporary, path, false);
                return path;
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        throw new IOException("No unused desktop script filename is available.");
    }

    internal static DesktopRebootResult Install(InstallationTargetKind kind, string deployment, Action<string> log, string language)
    {
        try
        {
            var path = Write(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Build(kind, deployment), language);
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
