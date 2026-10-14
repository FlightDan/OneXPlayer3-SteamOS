using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class SteamOSDesktopChecks
{
    internal static string Run()
    {
        var directory = Path.Combine(InstallationController.Work, "desktop-reboot-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var checks = new List<string>();
        void Require(bool value, string name) { if (!value) throw new IOException(name); checks.Add(name); }
        void Refuse(Action action, string name)
        { try { action(); } catch (IOException) { checks.Add(name); return; } throw new IOException("Accepted: " + name); }
        var entry = Convert.ToBase64String(new byte[] { 1, 0, 0, 0, 4, 0, 0, 0 });
        File.WriteAllText(Path.Combine(directory, "firmware-before.json"), JsonSerializer.Serialize(new { name = "Boot60AB", entry }));
        File.WriteAllText(Path.Combine(directory, "firmware-result.json"), JsonSerializer.Serialize(new { status = "registered", name = "Boot60AB" }));
        var content = SteamOSDesktop.Build(InstallationTargetKind.InternalShared, directory);
        Require(content.Contains("$name = 'Boot60AB'") && content.Contains("'" + entry + "'") && !content.Contains("@@"), "registered-entry-is-bound-to-script");
        Require(!content.Replace("\r\n", "").Contains('\n'), "cmd-crlf-line-endings");
        var desktop = Path.Combine(directory, "中文 desktop & 'quoted' % !"); Directory.CreateDirectory(desktop);
        var path = SteamOSDesktop.Write(desktop, content);
        Require(Path.GetFileName(path) == "重启到 SteamOS.bat", "chinese-desktop-name");
        Require(File.ReadAllText(path) == content && SteamOSDesktop.Write(desktop, content) == path, "unicode-desktop-and-idempotent-write");
        var english = SteamOSDesktop.Write(desktop, content, "en-US");
        Require(Path.GetFileName(english) == "Restart to SteamOS.bat" && SteamOSDesktop.Write(desktop, content, "en-US") == english, "english-desktop-name-and-idempotent-write");
        File.WriteAllText(english, "user English content");
        var englishSecond = SteamOSDesktop.Write(desktop, content, "en-US");
        Require(Path.GetFileName(englishSecond) == "Restart to SteamOS (2).bat" && File.ReadAllText(english) == "user English content", "preserve-existing-english-user-file");
        File.WriteAllText(path, "user content");
        var second = SteamOSDesktop.Write(desktop, content);
        Require(path != second && File.ReadAllText(path) == "user content", "preserve-existing-user-file");
        var external = SteamOSDesktop.Build(InstallationTargetKind.ExternalDisk, directory);
        Require(external.Contains("$name = ''") && !external.Contains("@@"), "external-firmware-menu-fallback");
        File.WriteAllText(Path.Combine(directory, "external.bat"), external);
        File.WriteAllText(Path.Combine(directory, "firmware-result.json"), JsonSerializer.Serialize(new { status = "registered", name = "Boot60AC" }));
        Refuse(() => SteamOSDesktop.Build(InstallationTargetKind.InternalShared, directory), "reject-inconsistent-registration");
        Refuse(() => SteamOSDesktop.Write(Path.Combine(directory, "missing"), content), "missing-desktop-rejected");
        return JsonSerializer.Serialize(new { checks, directory, internalBat = second, externalBat = Path.Combine(directory, "external.bat"), firmwareWritten = false, restartExecuted = false }, new JsonSerializerOptions { WriteIndented = true });
    }
}
