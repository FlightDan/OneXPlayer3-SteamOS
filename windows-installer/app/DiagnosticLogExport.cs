using System.IO;
using System.IO.Compression;
using System.Text;
using System.Text.Json;

namespace OxpInstaller;

internal static class DiagnosticLogExport
{
    internal static void Write(string destination, InstallationSession? session, string displayedLog, string? workspace = null)
    {
        workspace ??= InstallationController.Work;
        var target = Path.GetFullPath(destination);
        if (!target.EndsWith(".zip", StringComparison.OrdinalIgnoreCase)) throw new IOException("Choose a .zip archive filename.");
        var temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        var included = new List<string>();
        var skipped = new List<string>();
        try
        {
            using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            using (var archive = new ZipArchive(output, ZipArchiveMode.Create))
            {
                void Text(string name, string value)
                {
                    using var writer = new StreamWriter(archive.CreateEntry(name).Open(), new UTF8Encoding(false));
                    writer.Write(value);
                }
                void Collect(string directory, string prefix)
                {
                    if (!Directory.Exists(directory)) { skipped.Add(prefix + ": directory unavailable"); return; }
                    MediaSource.Ordinary(directory, workspace, false);
                    foreach (var path in Directory.EnumerateFiles(directory).Order(StringComparer.OrdinalIgnoreCase))
                    {
                        if (Path.GetExtension(path).ToLowerInvariant() is not (".log" or ".json" or ".jsonl" or ".txt")) continue;
                        var name = prefix + "/" + Path.GetFileName(path);
                        try
                        {
                            MediaSource.Ordinary(path, workspace);
                            // Snapshot length keeps export finite while the installer is still logging.
                            using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                            var remaining = input.Length;
                            using var entry = archive.CreateEntry(name, CompressionLevel.Fastest).Open();
                            var buffer = new byte[65536];
                            while (remaining > 0)
                            {
                                var count = input.Read(buffer, 0, (int)Math.Min(remaining, buffer.Length));
                                if (count == 0) break;
                                entry.Write(buffer, 0, count); remaining -= count;
                            }
                            included.Add(name);
                        }
                        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
                        { skipped.Add(name + ": " + error.Message); }
                    }
                }
                Text("displayed-log.txt", displayedLog);
                if (session != null)
                {
                    var directory = Path.Combine(workspace, "install-session-" + session.Id);
                    Collect(directory, "session");
                    // The persisted state includes deployment paths added after the initial UI callback.
                    try
                    {
                        var path = Path.Combine(directory, "session.json");
                        MediaSource.Ordinary(path, workspace);
                        session = JsonSerializer.Deserialize<InstallationSession>(File.ReadAllText(path)) ?? session;
                    }
                    catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
                    { skipped.Add("session metadata: " + error.Message); }
                    if (session.Deployment != null) Collect(session.Deployment, "deployment");
                }
                Text("export-info.json", JsonSerializer.Serialize(new
                {
                    exportedUtc = DateTime.UtcNow, version = ReleaseInfo.DisplayVersion,
                    windows = Environment.OSVersion.VersionString, runtime = Environment.Version.ToString(),
                    session, included, skipped,
                    scope = "Diagnostic text files only. Running tasks are exported as a snapshot. Disk images and binaries are excluded."
                }, new JsonSerializerOptions { WriteIndented = true }));
            }
            File.Move(temporary, target, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
