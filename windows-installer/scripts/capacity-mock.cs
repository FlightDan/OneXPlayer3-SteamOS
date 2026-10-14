using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

// Measurement-only entry point copied into an isolated build, never into the release app.
internal static class CapacityMock
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int kind, byte[] info, uint size);
    private static readonly object Gate = new();
    private static string run = "", stage = "starting";
    private static Stopwatch elapsed = new();
    private static StreamWriter events = null!, transcript = null!;
    private static readonly List<object> stages = new();
    private static object Inventory(string name, bool detail)
    {
        long logical = 0, allocated = 0; int count = 0, errors = 0;
        var groups = new Dictionary<string, (long Logical, long Allocated, int Count)>();
        var files = new List<object>();
        var paths = Directory.EnumerateFiles(run, "*", SearchOption.AllDirectories);
        var sharedWork = InstallationController.Work;
        var externalWork = !sharedWork.StartsWith(run+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase);
        if (externalWork) paths = paths.Concat(Directory.EnumerateFiles(sharedWork,"*",SearchOption.AllDirectories));
        foreach (var path in paths)
        {
            try
            {
                var info = new FileInfo(path);
                if ((info.Attributes & FileAttributes.ReparsePoint) != 0) continue;
                using var handle = CreateFileW(path, 0, 7, IntPtr.Zero, 3, 0, IntPtr.Zero);
                var standard = new byte[24];
                if (handle.IsInvalid || !GetFileInformationByHandleEx(handle, 1, standard, 24)) { errors++; continue; }
                long actual = BitConverter.ToInt64(standard, 0);
                var relative = externalWork && path.StartsWith(sharedWork+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)
                    ? Path.Combine("work",Path.GetRelativePath(sharedWork,path)) : Path.GetRelativePath(run, path);
                var group = relative.Split(Path.DirectorySeparatorChar)[0];
                var old = groups.GetValueOrDefault(group);
                groups[group] = (old.Logical + info.Length, old.Allocated + actual, old.Count + 1);
                logical += info.Length; allocated += actual; count++;
                if (detail) files.Add(new { path = relative, logical_bytes = info.Length, allocated_bytes = actual, sparse = info.Attributes.HasFlag(FileAttributes.SparseFile) });
            }
            catch (IOException) { errors++; }
        }
        var value = new { utc = DateTime.UtcNow, seconds = elapsed.Elapsed.TotalSeconds, stage, name, logical_bytes = logical,
            allocated_bytes = allocated, count, errors, available_bytes = MediaSpace.Available(run),
            groups = groups.ToDictionary(x => x.Key, x => new { logical_bytes = x.Value.Logical, allocated_bytes = x.Value.Allocated, count = x.Value.Count }), files = detail ? files : null };
        if (detail) File.WriteAllText(Path.Combine(run, "evidence", "inventory-" + name + ".json"), JsonSerializer.Serialize(value));
        return value;
    }
    private static void Event(object value) { lock (Gate) events.WriteLine(JsonSerializer.Serialize(value)); }
    private static void Log(string text)
    {
        lock (Gate) transcript.Write(text + (text.EndsWith('\n') ? "" : "\n"));
        Event(new { utc = DateTime.UtcNow, seconds = elapsed.Elapsed.TotalSeconds, stage, type = "log", text });
    }
    private static async Task<T> Step<T>(string name, Func<Task<T>> action)
    {
        stage = name;
        var start = elapsed.Elapsed.TotalSeconds;
        Event(new { type = "stage_start", name, seconds = start, utc = DateTime.UtcNow });
        Event(Inventory(name + "-before", true));
        try
        {
            T result = await action();
            var end = elapsed.Elapsed.TotalSeconds;
            var row = new { name, start_seconds = start, end_seconds = end, duration_seconds = end - start, passed = true };
            stages.Add(row); Event(row); Event(Inventory(name + "-after", true));
            File.WriteAllText(Path.Combine(run, "evidence", "stages.json"), JsonSerializer.Serialize(stages, new JsonSerializerOptions { WriteIndented = true }));
            return result;
        }
        catch (Exception error) { Event(new { type = "stage_failed", name, seconds = elapsed.Elapsed.TotalSeconds, error = error.ToString() }); throw; }
    }
    private static Task<string> Step(string name, Func<Task> action) => Step(name, async () => { await action(); return "done"; });
    internal static async Task<int> RunAsync(string root, string source)
    {
        run = Path.GetFullPath(root); Directory.CreateDirectory(Path.Combine(run, "evidence"));
        using var eventWriter = new StreamWriter(Path.Combine(run, "evidence/events.jsonl")) { AutoFlush = true };
        using var logWriter = new StreamWriter(Path.Combine(run, "evidence/full-transcript.log")) { AutoFlush = true };
        events = eventWriter; transcript = logWriter; elapsed = Stopwatch.StartNew();
        var readyImage = source.StartsWith("ready-image:",StringComparison.Ordinal);
        InstallerWorkspace.Select(readyImage?Path.GetDirectoryName(Path.GetDirectoryName(source[12..]))! : Path.Combine(run, "work")); InstallerI18n.SetLanguage("zh-CN");
        using var stop = new CancellationTokenSource();
        var sampler = Task.Run(async () => {
            while (!stop.IsCancellationRequested) {
                try { Event(Inventory("sample", false)); await Task.Delay(5000, stop.Token); }
                catch (OperationCanceledException) { break; }
                catch (Exception error) { Event(new { type = "sampling_error", error = error.ToString() }); }
            }
        });
        var token = CancellationToken.None;
        var session = Path.Combine(InstallationController.Work, "capacity-build-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(session);
        try
        {
            if (source == "default-zip")
            {
                source = await Step("00-recovery-download-default-zip", async () => {
                    var origin = AriaDownload.Origins()[0];
                    if (!origin.Url.EndsWith(".img.zip",StringComparison.OrdinalIgnoreCase)) throw new IOException("Latest default is not ZIP.");
                    var job = await AriaDownload.CreateAsync(origin.Url,token);
                    Event(new { type="download_origin",job });
                    job = await AriaDownload.RunAsync(job, p=>Event(new {type="download_progress",utc=DateTime.UtcNow,seconds=elapsed.Elapsed.TotalSeconds,stage,p.Completed,p.Total,p.Speed,p.Status}),token);
                    var contextPath = Path.Combine(run,"evidence/run-context.json");
                    var context = JsonNode.Parse(File.ReadAllText(contextPath))!;
                    context["recovery_archive_bytes"] = job.Remote.Length;
                    context["recovery_archive_format"] = "zip";
                    context["recovery_network_download_measured"] = true;
                    context["recovery_url"] = origin.Url;
                    File.WriteAllText(contextPath,context.ToJsonString(new JsonSerializerOptions{WriteIndented=true}));
                    return AriaDownload.ResultPath(job);
                });
            }
            var continuation = readyImage || source.StartsWith("prepared-qcow:",StringComparison.Ordinal);
            var options = InstallerOptions.Defaults;
            if (continuation) options = options with { Repairs = options.Repairs.Where(x=>x!="flathub-ustc").ToArray() };
            File.WriteAllText(Path.Combine(run,"evidence/options.json"), JsonSerializer.Serialize(options, new JsonSerializerOptions { WriteIndented = true }));
            var image = Path.Combine(session,"prepared.img");
            if (!continuation)
            {
                var imported = await Step("01-recovery-decompress", () => Backend.ImportAsync(source, Log, token));
                var updated = await Step("02-official-310-prepare-cached", () => OfficialSystem.PrepareAsync(imported, session, Log, token));
                var fixture = await Step("03-create-virtual-layout", () => Backend.CreateFixtureAsync(Log, token));
                await Step("04-linux-system-deployment", () => Backend.GuestAsync("deployment-test", updated, false, Log, token, fixture: fixture));
                await Step("05-sparse-raw-export", () => RawImageStaging.ConvertAsync(QcowReadOnlyGraph.Filename(fixture), image, Log, token));
            }
            else if (!readyImage)
                await Step("05-sparse-raw-export", () => RawImageStaging.ConvertAsync(QcowReadOnlyGraph.Filename(source[14..]), image, Log, token));
            else image = Path.GetFullPath(source[12..]);
            var choices = JsonSerializer.Serialize(options, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower });
            if (!readyImage)
            {
            var componentLog = await Step(continuation?"06-compatible-components":"06-default-components", () => Backend.GuestAsync("integration", image, true, Log, token, selection: choices));
            var componentResults = componentLog.Split('\n').Select(x=>x.Trim()).Where(x=>x.StartsWith("OXP_COMPONENT_RESULT=",StringComparison.Ordinal)).Select(x=>JsonDocument.Parse(x[21..]).RootElement.Clone()).ToArray();
            File.WriteAllText(Path.Combine(run,"evidence/components.json"),JsonSerializer.Serialize(componentResults,new JsonSerializerOptions{WriteIndented=true}));
            if (componentResults.Length == 0 || componentResults.Any(x=>x.GetProperty("status").GetString()!="files_installed")) throw new IOException("Selected components refused; no native target written.");
            await Step("07-components-readonly-verify", () => Backend.GuestAsync("integration-verify", image, false, Log, token, selection: choices));
            await Step("08-refind-install", () => RefindInstallation.StageAsync(image, session, new("SteamOS",5), null, Log, token));
            image = await Step("09-selected-64gib-capacity", () => PreparedCapacity.ExpandAsync(image,session,64L*1024*1024*1024,Log,token));
            await Step("10-physical-source-readiness", () => Backend.GuestAsync("physical-readiness", image, false, Log, token));
            }
            await Step("11-installed-filesystem-usage", () => Backend.GuestAsync("capacity-usage", image, false, Log, token));
            using (var prepared = new PreparedDiskImage(image)) File.WriteAllText(Path.Combine(run,"evidence/partition-layout.json"),JsonSerializer.Serialize(prepared.Layout,new JsonSerializerOptions{WriteIndented=true}));
            var deployment = Path.Combine(InstallationController.Work,"partition-deploy-"+Guid.NewGuid().ToString("N")); Directory.CreateDirectory(deployment);
            await Step("12-native-write-and-full-readback", () => PartitionDeploymentChecks.WritePreparedAsync(image,InstallationTargetKind.InternalShared,deployment,Log,token));
            var boot = await Step("13-independent-uefi-boot", () => PartitionDeploymentChecks.ProveBootAsync(deployment,InstallationTargetKind.InternalShared,Log,token));
            Event(Inventory("complete",true));
            File.WriteAllText(Path.Combine(run,"evidence/result.json"),JsonSerializer.Serialize(new { passed=true, continuation, selected_options=options, seconds=elapsed.Elapsed.TotalSeconds, image, deployment, boot,
                scope="Latest default official recovery ZIP download/import, cached official 3.10 root preparation and default Chinese components + rEFInd, 64 GiB system range, native Windows new owned VHD writes/full readback, protected fixture preservation, independent UEFI login. No real device or host firmware changes. Official 3.10 root download excluded; Linux deployment includes the existing production rehearsal's injected-failure/retry checks." },new JsonSerializerOptions{WriteIndented=true}));
            return 0;
        }
        catch (Exception error)
        {
            Log(error.ToString()); Event(Inventory("failed",true));
            File.WriteAllText(Path.Combine(run,"evidence/result.json"),JsonSerializer.Serialize(new { passed=false, stage, error=error.ToString(), seconds=elapsed.Elapsed.TotalSeconds },new JsonSerializerOptions{WriteIndented=true}));
            return 1;
        }
        finally { stop.Cancel(); await sampler; }
    }
}
