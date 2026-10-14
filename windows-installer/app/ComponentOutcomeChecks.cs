using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class ComponentOutcomeChecks
{
    internal static string Run()
    {
        var options = new SelectedOptions(1, ["keyboard"], ["decky"], "zh-CN", "system");
        JsonElement Row(string slot, string id, string status, bool safe = false) => JsonSerializer.SerializeToElement(new { slot, id, status, safe_to_skip = safe, reason = "Resource unavailable" });
        var rows = new[] { Row("A", "keyboard", "files_installed"), Row("A", "decky", "not_installed", true), Row("B", "keyboard", "files_installed"), Row("B", "decky", "not_installed", true) };
        ComponentOutcome.Validate(rows, options);
        void Reject(JsonElement[] invalid)
        {
            try { ComponentOutcome.Validate(invalid, options); }
            catch (IOException) { return; }
            throw new IOException("Unsafe component report was accepted");
        }
        Reject([]);
        Reject(rows[..3]);
        Reject([rows[0], rows[0], rows[2], rows[3]]);
        Reject([rows[0], Row("A", "decky", "not_installed"), rows[2], rows[3]]);
        Reject([rows[0], Row("A", "decky", "failed", true), rows[2], rows[3]]);
        Reject([rows[0], rows[1], rows[2], Row("C", "decky", "not_installed", true)]);
        return "Safe skips accepted; missing, duplicate, unsafe and unknown-slot reports rejected.";
    }
}
