using System.IO;
using System.Diagnostics;
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
        var portable = Path.Combine(directory, "portable-installer"); Directory.CreateDirectory(portable);
        foreach (var file in new[] { "firmware-before.json", "firmware-result.json" })
            File.Copy(Path.Combine(directory, file), Path.Combine(portable, file));
        var persistent = Path.Combine(directory, "Program Files 中文 & 'quoted' %PATH% !", "OXP3 SteamOS", "Boot");
        var installDesktop = Path.Combine(directory, "installed desktop"); Directory.CreateDirectory(installDesktop);
        var logs = new List<string>();
        var installed = SteamOSDesktop.InstallAt(InstallationTargetKind.InternalShared, portable, installDesktop, persistent, logs.Add, "en-US");
        Require(installed.Path is not null && installed.Warning is null, "persistent-install-succeeds");
        var core = Directory.GetFiles(persistent, "*.bat").Single();
        Require(File.ReadAllText(core) == content && !content.Contains(portable, StringComparison.OrdinalIgnoreCase)
            && content.Contains("public static class OxpDesktopFirmware") && !content.Contains("SteamOSInstaller.exe"), "persistent-core-is-complete-and-portable-independent");
        var launcher = File.ReadAllText(installed.Path!);
        Require(launcher == SteamOSDesktop.BuildLauncher(core) && launcher.All(character => character < 128)
            && !launcher.Contains(persistent) && !launcher.Contains(portable), "launcher-encodes-core-path-as-data");
        var repeat = SteamOSDesktop.InstallAt(InstallationTargetKind.InternalShared, portable, installDesktop, persistent, logs.Add, "en-US");
        Require(repeat.Path == installed.Path && Directory.GetFiles(persistent, "*.bat").Length == 1, "persistent-install-is-idempotent");
        File.WriteAllText(core, "administrator edited core");
        var replacement = SteamOSDesktop.PersistCore(persistent, content);
        Require(replacement != core && File.ReadAllText(core) == "administrator edited core"
            && SteamOSDesktop.PersistCore(persistent, content) == replacement, "edited-core-preserved-with-idempotent-suffix");
        File.WriteAllText(installed.Path!, "user edited launcher");
        var protectedInstall = SteamOSDesktop.InstallAt(InstallationTargetKind.InternalShared, portable, installDesktop, persistent, logs.Add, "en-US");
        Require(protectedInstall.Path != installed.Path && File.ReadAllText(installed.Path!) == "user edited launcher", "install-preserves-edited-desktop-launcher");
        Directory.Delete(portable, true);
        Require(File.Exists(replacement) && File.Exists(protectedInstall.Path), "persistent-core-and-launcher-survive-installer-deletion");

        // Run only a harmless replacement body through the actual production launcher.
        var safeCore = SteamOSDesktop.PersistCore(persistent,
            "# OXP3-POWERSHELL\r\n[IO.File]::WriteAllText($env:OXP3_LAUNCHER_PROOF, $env:OXP3_STEAMOS_BAT)\r\n");
        var safeLauncher = SteamOSDesktop.Write(desktop, SteamOSDesktop.BuildLauncher(safeCore), "en-US");
        var proof = Path.Combine(directory, "launcher-proof.txt");
        var start = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe"))
        {
            Arguments = "/d /v:off /c \"\"%OXP3_TEST_LAUNCHER%\"\"",
            UseShellExecute = false, CreateNoWindow = true
        };
        start.Environment["OXP3_TEST_LAUNCHER"] = safeLauncher;
        start.Environment["OXP3_LAUNCHER_PROOF"] = proof;
        using (var process = Process.Start(start)!)
        {
            if (!process.WaitForExit(30000)) { process.Kill(true); throw new IOException("Safe launcher timed out."); }
            Require(process.ExitCode == 0 && File.ReadAllText(proof) == safeCore, "real-launcher-loads-unicode-metacharacter-core-without-firmware-or-restart");
        }
        var blocked = Path.Combine(directory, "blocked-program-directory"); File.WriteAllText(blocked, "user file");
        var warning = SteamOSDesktop.InstallAt(InstallationTargetKind.ExternalDisk, directory, installDesktop, blocked, logs.Add, "en-US");
        Require(warning.Path is null && !string.IsNullOrEmpty(warning.Warning) && File.ReadAllText(blocked) == "user file"
            && logs.Any(line => line.StartsWith("DESKTOP_STEAMOS_SCRIPT_WARNING=")), "persistent-write-failure-is-warning-and-preserves-user-file");
        var missingDesktop = SteamOSDesktop.InstallAt(InstallationTargetKind.ExternalDisk, directory,
            Path.Combine(directory, "missing-desktop"), persistent, logs.Add, "en-US");
        Require(missingDesktop.Path is null && !string.IsNullOrEmpty(missingDesktop.Warning), "desktop-write-failure-is-warning");
        var missingProgramFiles = SteamOSDesktop.InstallAt(InstallationTargetKind.ExternalDisk, directory,
            installDesktop, "", logs.Add, "en-US");
        Require(missingProgramFiles.Path is null && !string.IsNullOrEmpty(missingProgramFiles.Warning), "missing-program-files-is-warning-without-relative-fallback");

        // Junctions require no symbolic-link privilege on Windows. Never follow them for writes.
        var junction = Path.Combine(directory, "linked-program-directory");
        var junctionStart = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe"))
        {
            Arguments = "/d /v:off /c mklink /J \"%OXP3_TEST_JUNCTION%\" \"%OXP3_TEST_TARGET%\"",
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true
        };
        junctionStart.Environment["OXP3_TEST_JUNCTION"] = junction;
        junctionStart.Environment["OXP3_TEST_TARGET"] = persistent;
        using (var process = Process.Start(junctionStart)!)
        {
            process.WaitForExit();
            Require(process.ExitCode == 0, "reparse-point-fixture-created");
        }
        try
        {
            Refuse(() => SteamOSDesktop.PersistCore(junction, content), "reject-persistent-directory-reparse-point");
            Refuse(() => SteamOSDesktop.PersistCore(Path.Combine(junction, "nested"), content), "reject-persistent-ancestor-reparse-point");
            var redirectedDesktop = SteamOSDesktop.Write(junction, "desktop launcher fixture");
            Require(File.ReadAllText(redirectedDesktop) == "desktop launcher fixture", "redirected-user-desktop-remains-supported");
        }
        finally { Directory.Delete(junction); }
        var linkedFiles = Path.Combine(directory, "linked-files"); Directory.CreateDirectory(linkedFiles);
        var fileLink = Path.Combine(linkedFiles, Path.GetFileName(core));
        junctionStart.Environment["OXP3_TEST_JUNCTION"] = fileLink;
        using (var process = Process.Start(junctionStart)!)
        {
            process.WaitForExit();
            Require(process.ExitCode == 0, "reparse-point-script-filename-fixture-created");
        }
        try { Refuse(() => SteamOSDesktop.PersistCore(linkedFiles, content), "reject-persistent-file-reparse-point"); }
        finally { Directory.Delete(fileLink); }
        File.WriteAllText(Path.Combine(directory, "firmware-result.json"), JsonSerializer.Serialize(new { status = "registered", name = "Boot60AC" }));
        Refuse(() => SteamOSDesktop.Build(InstallationTargetKind.InternalShared, directory), "reject-inconsistent-registration");
        Refuse(() => SteamOSDesktop.Write(Path.Combine(directory, "missing"), content), "missing-desktop-rejected");
        return JsonSerializer.Serialize(new { checks, directory, internalBat = second, externalBat = Path.Combine(directory, "external.bat"), firmwareWritten = false, restartExecuted = false }, new JsonSerializerOptions { WriteIndented = true });
    }
}
