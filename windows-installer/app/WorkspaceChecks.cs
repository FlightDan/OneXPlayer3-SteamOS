using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace OxpInstaller;

internal static class WorkspaceChecks
{
    internal static async Task<string> RunAsync()
    {
        var results = new List<string>();
        void Require(bool ok, string label) { if (!ok) throw new IOException(label); results.Add(label); }
        var original = InstallerWorkspace.DirectoryPath;
        var settings = Path.Combine(Backend.Root, "workspace.json");
        var previous = File.Exists(settings) ? File.ReadAllBytes(settings) : null;
        var directory = Path.Combine(Backend.Root, "work", "workspace-check-" + Guid.NewGuid().ToString("N"), "自选 空间");
        try {
            InstallerWorkspace.Select(directory);
            Require(InstallationController.Work == directory && AriaDownload.Root == Path.Combine(directory, "downloads"), "selected-workspace-routes-sessions-and-downloads");
            await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe"),
                [typeof(App).Assembly.Location, "--cli", "workspace-path"], _ => { }, CancellationToken.None);
            Require(File.ReadAllText(Path.Combine(Backend.Root, "logs/native-cli-result.txt")).Contains(directory), "new-process-loads-selected-workspace");
            bool rejected = false;
            try { MediaSource.Ordinary(Path.Combine(original, "outside.img"), directory, false); } catch (IOException) { rejected = true; }
            Require(rejected, "selected-workspace-retains-path-containment");
            rejected = false;
            try { InstallerWorkspace.Normalize(Path.GetPathRoot(directory)!); } catch (IOException) { rejected = true; }
            Require(rejected, "drive-root-is-not-a-workspace");
            var qemu = Path.Combine(Backend.Root, "runtime/qemu-min/qemu-img.exe");
            var empty = Path.Combine(directory, "empty.qcow2");
            await Backend.ProcessAsync(qemu, ["create", "-f", "qcow2", empty, "80G"], _ => { }, CancellationToken.None);
            var sparse = Path.Combine(directory, "empty.img");
            await RawImageStaging.ConvertAsync(empty, sparse, _ => { }, CancellationToken.None);
            Require(new FileInfo(sparse).Length == InstallationController.Capacity && (File.GetAttributes(sparse) & FileAttributes.SparseFile) != 0,
                "80-GiB-image-keeps-sparse-allocation");
            using (var info = JsonDocument.Parse(await Backend.ProcessAsync(qemu, ["info", "--output=json", sparse], _ => { }, CancellationToken.None)))
                Require(info.RootElement.GetProperty("actual-size").GetInt64() < 1024 * 1024, "empty-80-GiB-image-uses-less-than-1-MiB");
            var source = Path.Combine(directory, "data.img");
            using (var stream = new FileStream(source, FileMode.CreateNew, FileAccess.Write)) {
                stream.SetLength(16 * 1024 * 1024);
                stream.Write(new byte[] { 1, 2, 3, 4 });
                stream.Position = stream.Length - 4; stream.Write(new byte[] { 5, 6, 7, 8 });
            }
            var copy = Path.Combine(directory, "data-copy.img");
            await RawImageStaging.ConvertAsync(source, copy, _ => { }, CancellationToken.None);
            await Backend.ProcessAsync(qemu, ["compare", "-f", "raw", "-F", "raw", source, copy], _ => { }, CancellationToken.None);
            results.Add("sparse-copy-preserves-start-end-data-and-zero-regions");
            var snapshot = JsonNode.Parse(PartitionInventory.ExampleJson)!;
            snapshot[0]!["partitionReadError"] = "incomplete";
            Require(PartitionInventory.Read(snapshot.ToJsonString()).Single().Rows.All(row => row.Space == null && !row.CanDelete), "incomplete-inventory-cannot-install-or-delete");
            Require(DiskPlanning.FreeSpaces(snapshot.ToJsonString()).Count == 0, "incomplete-inventory-cannot-create-a-plan");
            Require(MediaSpace.InstallationBudget(true, false) == 45ul * 1024 * 1024 * 1024
                && MediaSpace.InstallationBudget(true, true) == 45ul * 1024 * 1024 * 1024
                && MediaSpace.InstallationBudget(false, false) == 125ul * 1024 * 1024 * 1024, "45-GiB-minimum-excludes-rehearsal-target");
            return JsonSerializer.Serialize(new { passed = true, directory, results }, new JsonSerializerOptions { WriteIndented = true });
        } finally {
            InstallerWorkspace.Select(original);
            if (previous != null) File.WriteAllBytes(settings, previous); else File.Delete(settings);
        }
    }
}
