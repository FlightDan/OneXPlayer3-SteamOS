using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class ComponentOutcomeChecks
{
    internal static string Run()
    {
        var options = new SelectedOptions(1, ["keyboard"], ["decky"], "zh-CN", "system");
        JsonElement Row(string slot, string id, string status, bool safe = false) => JsonSerializer.SerializeToElement(new { slot, id, status, safe_to_skip = safe, reason = "Resource unavailable" });
        var rows = new[] { Row("A", "keyboard", "files_installed"), Row("A", "decky", "not_installed", true), Row("A", "system-update-policy", "files_installed"),
            Row("B", "keyboard", "files_installed"), Row("B", "decky", "not_installed", true), Row("B", "system-update-policy", "files_installed") };
        ComponentOutcome.Validate(rows, options);
        ComponentOutcome.Validate([], new SelectedOptions(1, [], [], "zh-CN", "system"));
        var accessOptions = new SelectedOptions(1, [], [], "zh-CN", "system", SetDeckPassword: true);
        ComponentOutcome.Validate([Row("A", "deck-access", "files_installed"), Row("A", "system-update-policy", "files_installed"),
            Row("B", "deck-access", "files_installed"), Row("B", "system-update-policy", "files_installed")], accessOptions);
        var languageOptions = new SelectedOptions(1, [], [], "zh-CN", "ja_JP");
        ComponentOutcome.Validate([Row("A", "kde-language", "files_installed"), Row("A", "system-update-policy", "files_installed"),
            Row("B", "kde-language", "files_installed"), Row("B", "system-update-policy", "files_installed")], languageOptions);
        void Reject(JsonElement[] invalid)
        {
            try { ComponentOutcome.Validate(invalid, options); }
            catch (IOException) { return; }
            throw new IOException("Unsafe component report was accepted");
        }
        Reject([]);
        Reject(rows[..5]);
        Reject([rows[0], rows[0], rows[2], rows[3], rows[4], rows[5]]);
        Reject([rows[0], Row("A", "decky", "not_installed"), rows[2], rows[3], rows[4], rows[5]]);
        Reject([rows[0], Row("A", "decky", "failed", true), rows[2], rows[3], rows[4], rows[5]]);
        Reject([rows[0], rows[1], Row("A", "system-update-policy", "not_installed", true), rows[3], rows[4], rows[5]]);
        Reject([rows[0], rows[1], rows[2], rows[3], rows[4], Row("C", "decky", "not_installed", true)]);
        return "Policy is required for repairs, plugins, access or KDE language selections; safe component skips are accepted; missing, duplicate, unsafe, skippable-policy and unknown-slot reports are rejected.";
    }
}
