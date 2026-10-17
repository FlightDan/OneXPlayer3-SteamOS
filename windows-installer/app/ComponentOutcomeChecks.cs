using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class ComponentOutcomeChecks
{
    internal static string Run()
    {
        var missingOptions = new InstallationRequest(InstallationTargetKind.InternalShared, "absent.img", false, Physical: true);
        var omittedOptions = JsonSerializer.Deserialize<InstallationRequest>("{\"Kind\":0,\"Source\":\"absent.img\",\"Prepared\":false,\"Physical\":true}")!;
        foreach (var request in new[] { missingOptions, omittedOptions })
        {
            try { InstallationController.ValidateRequest(request); }
            catch (IOException error) when (error.Message.Contains("Physical installation options are required", StringComparison.Ordinal)) { continue; }
            throw new IOException("Physical installation without options was not rejected before disk/source validation");
        }
        var options = new SelectedOptions(1, ["keyboard"], ["decky"], "zh-CN", "system");
        JsonElement Row(string slot, string id, string status, bool safe = false) => JsonSerializer.SerializeToElement(new { slot, id, status, safe_to_skip = safe, reason = "Resource unavailable",
            os_image_updates = id == "system-update-hold" ? "held" : null, steam_client_updates = id == "system-update-hold" ? "unchanged" : null });
        var maintenance = new[] { Row("A", "maintenance-tool", "files_installed"), Row("B", "maintenance-tool", "files_installed") };
        var console = new[] { Row("A", "serial-console-policy", "files_installed"), Row("B", "serial-console-policy", "files_installed") };
        JsonElement[] hold = [Row("A", "system-update-hold", "files_installed"), Row("B", "system-update-hold", "files_installed"), ..console, ..maintenance];
        JsonElement[] rows = [Row("A", "keyboard", "files_installed"), Row("A", "decky", "not_installed", true),
            Row("B", "keyboard", "files_installed"), Row("B", "decky", "not_installed", true), ..hold];
        ComponentOutcome.Validate(rows, options);
        ComponentOutcome.Validate(hold, new SelectedOptions(1, [], [], "zh-CN", "system"));
        var accessOptions = new SelectedOptions(1, [], [], "zh-CN", "system", SetDeckPassword: true);
        ComponentOutcome.Validate([..hold, Row("A", "deck-access", "files_installed"), Row("B", "deck-access", "files_installed")], accessOptions);
        var languageOptions = new SelectedOptions(1, [], [], "zh-CN", "ja_JP");
        ComponentOutcome.Validate([..hold, Row("A", "kde-language", "files_installed"), Row("B", "kde-language", "files_installed")], languageOptions);
        var storageOptions = new SelectedOptions(1, [], [], "zh-CN", "system", StorageMounts:
            [new StorageMount("11111111-2222-3333-4444-555555555555", "exfat", "share-d1-p1")]);
        ComponentOutcome.Validate([..hold, Row("A", "shared-storage", "not_installed", true), Row("B", "shared-storage", "not_installed", true)], storageOptions);
        ComponentOutcome.Validate([..hold, Row("A", "shared-storage", "files_installed"), Row("B", "shared-storage", "not_installed", true)], storageOptions);
        void RejectStorage(JsonElement[] invalid)
        {
            try { ComponentOutcome.Validate([..hold, ..invalid], storageOptions); }
            catch (IOException) { return; }
            throw new IOException("Unsafe shared storage report was accepted");
        }
        RejectStorage([]);
        RejectStorage([Row("A", "shared-storage", "not_installed"), Row("B", "shared-storage", "files_installed")]);
        RejectStorage([Row("A", "shared-storage", "failed", true), Row("B", "shared-storage", "files_installed")]);
        RejectStorage([JsonSerializer.SerializeToElement(new { slot = "A", id = "shared-storage", status = "not_installed", safe_to_skip = true, reason = " " }), Row("B", "shared-storage", "files_installed")]);
        RejectStorage([JsonSerializer.SerializeToElement(new { slot = "A", id = "shared-storage", status = "not_installed", safe_to_skip = true, reason = true }), Row("B", "shared-storage", "files_installed")]);
        void Reject(JsonElement[] invalid)
        {
            try { ComponentOutcome.Validate(invalid, options); }
            catch (IOException) { return; }
            throw new IOException("Unsafe component report was accepted");
        }
        Reject([]);
        Reject(rows[..3]);
        Reject([rows[0], rows[0], rows[2], rows[3], ..hold]);
        Reject([rows[0], Row("A", "decky", "not_installed"), rows[2], rows[3], ..hold]);
        Reject([rows[0], Row("A", "decky", "failed", true), rows[2], rows[3], ..hold]);
        Reject(rows[..4]);
        Reject(rows[..5]);
        Reject([..rows, hold[0]]);
        Reject([..rows[..4], Row("A", "system-update-hold", "not_installed", true), hold[1], ..console, ..maintenance]);
        Reject([..rows[..4], JsonSerializer.SerializeToElement(new { slot = "A", id = "system-update-hold", status = "files_installed", os_image_updates = "allowed", steam_client_updates = "unchanged" }), hold[1], ..console, ..maintenance]);
        Reject([..rows[..4], JsonSerializer.SerializeToElement(new { slot = "A", id = "system-update-hold", status = "files_installed" }), hold[1], ..console, ..maintenance]);
        Reject(rows.Where(x => x.GetProperty("id").GetString() != "serial-console-policy").ToArray());
        Reject([..rows.Where(x => x.GetProperty("id").GetString() != "serial-console-policy"), Row("A", "serial-console-policy", "not_installed", true), console[1]]);
        Reject([..rows, Row("A", "system-update-policy", "files_installed"), Row("B", "system-update-policy", "files_installed")]);
        Reject([..rows, Row("A", "system-update-policy", "not_installed", true), Row("B", "system-update-policy", "not_installed", true)]);
        Reject(rows.Where(x => x.GetProperty("id").GetString() != "maintenance-tool").ToArray());
        Reject([..rows.Where(x => x.GetProperty("id").GetString() != "maintenance-tool"), Row("A", "maintenance-tool", "not_installed", true), maintenance[1]]);
        Reject([rows[0], rows[1], rows[2], Row("C", "decky", "not_installed", true), ..hold]);
        return "Both slots require a successful OS update hold while Steam client updates remain unchanged; missing, duplicate, skipped or invalid hold reports are rejected. Existing optional component and shared-storage skip checks also pass.";
    }
}
