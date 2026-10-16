using System.IO;
using System.Text.Json;

namespace OxpInstaller;

internal static class ComponentOutcome
{
    internal static void Validate(JsonElement[] results, SelectedOptions options)
    {
        var expected = options.Repairs.Concat(options.Plugins).ToHashSet();
        expected.Add("system-update-hold");
        expected.Add("serial-console-policy");
        expected.Add("maintenance-tool");
        if (options.KdeLanguage != "system") expected.Add("kde-language");
        if (options.SetDeckPassword || options.EnableSsh) expected.Add("deck-access");
        if (options.StorageMounts is { Length: > 0 }) expected.Add("shared-storage");
        var optional = options.Repairs.Concat(options.Plugins).ToHashSet();
        if (options.StorageMounts is { Length: > 0 }) optional.Add("shared-storage");
        foreach (var slot in new[] { "A", "B" })
        {
            var records = results.Where(x => x.GetProperty("slot").GetString() == slot).ToArray();
            var ids = records.Select(x => x.GetProperty("id").GetString()!).ToArray();
            if (ids.Length != expected.Count || !expected.SetEquals(ids))
                throw new IOException("组件报告缺失或重复，不能继续安装。 / Missing or duplicate component results.");
            foreach (var record in records)
            {
                if (record.GetProperty("id").GetString() == "system-update-hold"
                    && (!record.TryGetProperty("os_image_updates", out var osUpdates) || osUpdates.ValueKind != JsonValueKind.String || osUpdates.GetString() != "held"
                        || !record.TryGetProperty("steam_client_updates", out var clientUpdates) || clientUpdates.ValueKind != JsonValueKind.String || clientUpdates.GetString() != "unchanged"))
                    throw new IOException("系统更新保护报告无效，不能继续安装。 / Invalid system update hold result.");
                if (record.GetProperty("status").GetString() == "files_installed") continue;
                if (record.GetProperty("status").GetString() != "not_installed"
                    || !record.TryGetProperty("safe_to_skip", out var safe) || safe.ValueKind != JsonValueKind.True
                    || !record.TryGetProperty("reason", out var reason) || reason.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(reason.GetString())
                    || !optional.Contains(record.GetProperty("id").GetString()!))
                    throw new IOException("组件未安全完成，不能继续安装。 / Component did not complete safely.");
            }
        }
        if (results.Length != expected.Count * 2) throw new IOException("Unexpected component result slot.");
    }
}
