using System.IO;
using System.Text.Json;

namespace OxpInstaller;

public static class InstallerWorkspace
{
    private static string Settings => Path.Combine(Backend.Root, "workspace.json");
    public static string? LoadError { get; private set; }
    public static string DirectoryPath { get; private set; } = Load();
    private static string Load()
    {
        if (!File.Exists(Settings)) return Path.Combine(Backend.Root, "work");
        try { return Normalize(JsonSerializer.Deserialize<string>(File.ReadAllText(Settings))
            ?? throw new IOException("Invalid workspace setting.")); }
        catch (Exception error) when (error is IOException or JsonException or ArgumentException or UnauthorizedAccessException) {
            LoadError = error.Message;
            return Path.Combine(Backend.Root, "work");
        }
    }
    internal static string Normalize(string path)
    {
        if (!Path.IsPathFullyQualified(path) || path.StartsWith(@"\\", StringComparison.Ordinal))
            throw new IOException("请选择本地磁盘上的文件夹。 / Choose a folder on a local disk.");
        path = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        if (string.Equals(path, Path.GetPathRoot(path), StringComparison.OrdinalIgnoreCase))
            throw new IOException("请选择专用子文件夹，不能直接使用盘符根目录。 / Choose a dedicated subfolder.");
        MediaSource.Ordinary(Path.Combine(path, "workspace-probe"), path, false);
        return path;
    }
    public static void Select(string path)
    {
        path = Normalize(path);
        Directory.CreateDirectory(path);
        var probe = Path.Combine(path, ".write-check-" + Guid.NewGuid().ToString("N"));
        using (new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose)) { }
        // Persist next to the portable installer so elevated helpers use the same scope.
        File.WriteAllText(Settings + ".tmp", JsonSerializer.Serialize(path));
        File.Move(Settings + ".tmp", Settings, true);
        DirectoryPath = path;
        LoadError = null;
    }
}
