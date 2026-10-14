using System.IO;
using System.Text.Json;

namespace OxpInstaller;

public sealed record RefindChoice(string DefaultSystem, int Timeout);

public static class RefindInstallation
{
    public static string? WindowsEsp(PartitionSelection? selection)
    {
        if (selection == null || selection.Example) return null;
        using var doc = JsonDocument.Parse(selection.Snapshot);
        var candidates = doc.RootElement.EnumerateArray().SelectMany(d => d.GetProperty("partitions").EnumerateArray())
            .Where(p => p.TryGetProperty("isSystem", out var system) && system.ValueKind == JsonValueKind.True
                && p.TryGetProperty("gptType", out var type) && Guid.TryParse(type.GetString(), out var id)
                && id == new Guid("c12a7328-f81f-11d2-ba4b-00a0c93ec93b"))
            .Select(p => Guid.Parse(p.GetProperty("guid").GetString()!).ToString()).Distinct().ToArray();
        if (candidates.Length > 1) throw new IOException("Windows EFI 分区不唯一，请重新检查磁盘。 / Ambiguous Windows ESP.");
        return candidates.SingleOrDefault();
    }
    public static void Validate(RefindChoice choice, PartitionSelection? selection)
    {
        if (choice.DefaultSystem is not ("SteamOS" or "Windows") || choice.Timeout is < 0 or > 3600)
            throw new IOException("Invalid rEFInd settings.");
        if (choice.DefaultSystem == "Windows" && WindowsEsp(selection) == null)
            throw new IOException("未识别到当前 Windows 的 EFI 分区，请选择默认启动 SteamOS。 / Windows ESP was not identified; choose SteamOS.");
    }
    public static async Task StageAsync(string image, string directory, RefindChoice choice, PartitionSelection? selection, Action<string> log, CancellationToken token)
    {
        Validate(choice, selection);
        var json = JsonSerializer.Serialize(new { action="install", default_system=choice.DefaultSystem, timeout=choice.Timeout, windows_esp=WindowsEsp(selection) });
        await File.WriteAllTextAsync(Path.Combine(directory,"refind-choice.json"),json,token);
        var result = await Backend.GuestAsync("refind-image",image,true,log,token,selection:json);
        await File.WriteAllTextAsync(Path.Combine(directory,"refind-install.log"),result,token);
    }
}
