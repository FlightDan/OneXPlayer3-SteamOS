using System.Text.Json;

namespace OxpInstaller;

public static class ReleaseInfo
{
    public static string DisplayVersion { get; } = ReadDisplayVersion();

    private static string ReadDisplayVersion()
    {
        using var stream = typeof(ReleaseInfo).Assembly.GetManifestResourceStream("OxpInstaller.release.json")
            ?? throw new InvalidOperationException("Missing bundled release metadata.");
        using var document = JsonDocument.Parse(stream);
        return document.RootElement.GetProperty("display_version").GetString()
            ?? throw new InvalidOperationException("Missing release display version.");
    }
}
