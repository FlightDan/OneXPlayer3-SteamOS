using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Security.Principal;
using System.Text.Json;
using System.Text;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public sealed record InstallationRequest(InstallationTargetKind Kind, string Source, bool Prepared, SelectedOptions? Options = null, PartitionSelection? PlannedPartition = null, bool Physical = false, bool UpgradeTo310 = false, RefindChoice? Refind = null, string? InitialDeckPassword = null, bool MakeDefaultBoot = false);
public sealed record InstallationProgress(string Stage, string Message, double? Percent = null, string? Step = null);
public sealed record InstallationSession(int Schema, string Id, InstallationTargetKind Kind, string Source, bool Prepared,
    string Status, string Stage, string? Deployment, string? Error, DateTime UpdatedUtc, SelectedOptions? Options = null, bool Physical = false, RefindChoice? Refind = null, bool MakeDefaultBoot = false,
    string? DesktopRebootScript = null, string? DesktopRebootWarning = null);
public sealed record PartitionJob(int Schema, string Nonce, string Scope, InstallationTargetKind Kind, MediaSource Source, string? RecoveryState = null, PhysicalPlan? PhysicalPlan = null);
public sealed record PartitionJobResult(string Status, string? Error);

public static partial class InstallationController
{
    public const long Capacity = 80L * 1024 * 1024 * 1024;
    public static string Work => InstallerWorkspace.DirectoryPath;
    public static void Save(string path, InstallationSession state)
    {
        MediaSource.Ordinary(path, Work, false);
        MediaSource.Ordinary(path + ".tmp", Work, false);
        using (var file = new FileStream(path + ".tmp", FileMode.Create, FileAccess.Write, FileShare.None))
        { JsonSerializer.Serialize(file, state, new JsonSerializerOptions { WriteIndented = true }); file.Flush(true); }
        File.Move(path + ".tmp", path, true);
    }
    public static InstallationSession? Latest()
    {
        if (!Directory.Exists(Work)) return null;
        foreach (var directory in Directory.GetDirectories(Work, "install-session-*").OrderByDescending(Directory.GetLastWriteTimeUtc))
        {
            try
            {
                var path = Path.Combine(directory, "session.json"); MediaSource.Ordinary(path, Work);
                if (new FileInfo(path).Length > 65536) continue;
                var state = JsonSerializer.Deserialize<InstallationSession>(File.ReadAllText(path));
                if (state?.Schema == 1 && "install-session-" + state.Id == Path.GetFileName(directory) && Regex.IsMatch(state.Id, "^[0-9a-f]{32}$")) return state;
            }
            catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException) { }
        }
        return null;
    }
    public static string SessionDirectory(InstallationSession state) => Path.Combine(Work, "install-session-" + state.Id);
    public static void ValidateRequest(InstallationRequest request)
    {
        if (request.Physical && request.Options is null)
            throw new IOException("实际安装缺少配置，请重新选择安装内容。 / Physical installation options are required for system update protection.");
        if (request.MakeDefaultBoot && (!request.Physical || request.Kind != InstallationTargetKind.InternalShared))
            throw new IOException("仅内置实盘安装可修改当前电脑的默认启动项。 / Only internal physical installation can change this PC's default boot entry.");
        if (request.PlannedPartition != null)
        {
            if (!request.Physical && request.Kind != InstallationTargetKind.InternalShared) throw new IOException("A shared-space plan cannot be used for an external whole-disk rehearsal.");
            request.PlannedPartition.Target();
        }
        if(request.Physical && (request.PlannedPartition==null || request.PlannedPartition.Example)) throw new IOException("实际安装必须选择真实磁盘的未分配空间。 / Select real unallocated disk space.");
        if (request.Options != null) InstallerOptions.Validate(request.Options);
        SharedStorage.ValidateSelection(request.Options?.StorageMounts, request.PlannedPartition?.Snapshot);
        if (request.Options?.SetDeckPassword == true)
        {
            var password = request.InitialDeckPassword;
            if (string.IsNullOrEmpty(password) || password.Length < 8 || Encoding.UTF8.GetByteCount(password) > 255 || password.Any(c => c is '\0' or '\r' or '\n'))
                throw new IOException(InstallerI18n.Language == "en-US" ? "The deck password must be at least 8 characters and at most 255 UTF-8 bytes." : "deck 密码至少 8 个字符，最多 255 个 UTF-8 字节。");
        }
        else if (request.InitialDeckPassword != null) throw new IOException("A deck password was supplied while password setup is disabled.");
        if (request.Refind != null) RefindInstallation.Validate(request.Refind, request.PlannedPartition);
        if (!Enum.IsDefined(request.Kind)) throw new IOException("请选择安装位置。");
        if (string.IsNullOrWhiteSpace(request.Source) || !File.Exists(request.Source)) throw new IOException("请选择存在的系统镜像。");
        if (request.Prepared)
        {
            using var image = new PreparedDiskImage(request.Source);
            if (image.Layout.Size != Capacity) throw new IOException("演练需要本工具生成的 80 GiB 预部署镜像。");
        }
        else if (!(request.Source.EndsWith(".img", StringComparison.OrdinalIgnoreCase) || request.Source.EndsWith(".img.bz2", StringComparison.OrdinalIgnoreCase) || request.Source.EndsWith(".img.zip", StringComparison.OrdinalIgnoreCase)))
            throw new IOException("请选择 .img、.img.bz2 或 .img.zip 恢复镜像。");
        if (!request.Prepared && request.UpgradeTo310) OfficialSystem.RequirePreparedSource();
        Directory.CreateDirectory(Work);
        MediaSpace.RequireAvailable(Work, MediaSpace.InstallationBudget(request.Physical, request.Prepared));
    }
    public static async Task<InstallationSession> RunAsync(InstallationRequest request, Action<InstallationProgress> report, Action<string> log,
        CancellationToken token, Action<InstallationSession>? created = null)
        => await WithInstallationLogAsync("install", log, trace => RunCoreAsync(request,
            update => { trace.Progress(update); report(update); }, trace.Write, token, state =>
            {
                trace.Write($"\nINSTALL_SESSION={Path.Combine(SessionDirectory(state), "session.json")}\n");
                created?.Invoke(state);
            }));

    private static async Task<T> WithInstallationLogAsync<T>(string kind, Action<string> log, Func<InstallationLog, Task<T>> action)
    {
        using var trace = new InstallationLog(kind, log);
        trace.Write($"Installation log: {trace.LogPath}\nWorkspace: {Work}\n");
        try
        {
            var result = await action(trace);
            if (result is InstallationSession state)
                trace.Write($"\nINSTALL_STATUS={state.Status}\nDeployment: {state.Deployment}\n");
            return result;
        }
        catch (Exception error) { trace.Write(error.ToString() + Environment.NewLine); throw; }
    }

    private static async Task<InstallationSession> RunCoreAsync(InstallationRequest request, Action<InstallationProgress> report, Action<string> log,
        CancellationToken token, Action<InstallationSession>? created)
    {
        ValidateRequest(request); token.ThrowIfCancellationRequested();
        if (request.Physical && request.Options?.StorageMounts is { Length: > 0 } mounts)
        {
            using var inventoryTimeout = CancellationTokenSource.CreateLinkedTokenSource(token);
            inventoryTimeout.CancelAfter(TimeSpan.FromSeconds(30));
            var fresh = await Backend.PowerShellAsync("read-disks.ps1", [], _ => { }, inventoryTimeout.Token);
            SharedStorage.Revalidate(mounts, request.PlannedPartition!.Snapshot, fresh);
        }
        Directory.CreateDirectory(Work);
        var id = Guid.NewGuid().ToString("N"); var directory = Path.Combine(Work, "install-session-" + id); Directory.CreateDirectory(directory);
        var journal = Path.Combine(directory, "session.json");
        using var sessionLease = LeaseSession(directory);
        var state = new InstallationSession(1, id, request.Kind, Path.GetFullPath(request.Source), request.Prepared, "running", "preparing", null, null, DateTime.UtcNow, request.Options, request.Physical, request.Refind, request.MakeDefaultBoot);
        Save(journal, state); created?.Invoke(state);
        var progress = new InstallationProgressTracker();
        using var progressLog = new StreamWriter(new FileStream(Path.Combine(directory, "progress.jsonl"), FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
        var publish = report; var step = "01.01";
        report = value =>
        {
            value = value with { Percent = value.Percent ?? progress.Percent, Step = value.Step ?? step };
            lock (progressLog) progressLog.WriteLine(JsonSerializer.Serialize(new { utc = DateTime.UtcNow, value.Stage, value.Step, value.Percent, value.Message }));
            publish(value);
        };
        void Phase(string phase, string text, string code)
        { step = code; state = state with { Stage = phase, UpdatedUtc = DateTime.UtcNow }; Save(journal, state); report(new(phase, text)); }
        try
        {
            if (request.PlannedPartition != null)
                await File.WriteAllTextAsync(Path.Combine(directory, "partition-plan.json"), JsonSerializer.Serialize(new {
                    scope = request.Physical ? "reviewed unallocated physical range" : "independent virtual disk", allowPhysicalWrite = request.Physical,
                    selection = request.PlannedPartition, after = PartitionInventory.After(request.PlannedPartition)
                }, new JsonSerializerOptions { WriteIndented = true }), token);
            var image = request.Source;
            if (!request.Prepared)
            {
                Phase("preparing", "正在解压并准备系统镜像…", "01.01");
                var imported = await Backend.ImportAsync(image, log, token);
                progress.Advance("preparing", 2d / 32);
                if(request.UpgradeTo310)
                {
                    Phase("preparing","正在准备官方 SteamOS 3.10 系统…", "01.02");
                    imported = await OfficialSystem.PrepareAsync(imported, directory, log, token, update =>
                    {
                        step = update.Step;
                        report(new("preparing", update.Message,
                            progress.Advance("preparing", (2 + 10 * update.Fraction) / 32), update.Step));
                    });
                }
                progress.Advance("preparing", 12d / 32);
                Phase("preparing", "正在创建独立测试盘…", "01.03");
                var fixture = await Backend.CreateFixtureAsync(log, token);
                progress.Advance("preparing", 16d / 32);
                Phase("preparing", "正在准备 SteamOS 系统，这一步可能需要较长时间…", "01.04");
                await Backend.GuestAsync("deployment-test", imported, false, log, token, fixture: fixture);
                progress.Advance("preparing", 29d / 32);
                Phase("preparing", "正在导出可写入的系统内容…", "01.05");
                image = Path.Combine(directory, "prepared.img");
                await RawImageStaging.ConvertAsync(QcowReadOnlyGraph.Filename(fixture), image, log, token);
            }
            progress.Advance("preparing", 1);
            token.ThrowIfCancellationRequested();
            if (request.Options != null)
            {
                Phase("components", InstallerI18n.T("正在配置所选修复、插件与 KDE 语言…"), "02.01");
                var expected = 2 * (3 + request.Options.Repairs.Length + request.Options.Plugins.Length + (request.Options.KdeLanguage == "system" ? 0 : 1)
                    + (request.Options.SetDeckPassword || request.Options.EnableSsh ? 1 : 0)
                    + (request.Options.StorageMounts is { Length: > 0 } ? 1 : 0));
                var componentMessage = InstallerI18n.T("正在配置所选修复、插件与 KDE 语言…");
                void ComponentLog(string text)
                {
                    log(text);
                    bool changed;
                    lock (progress) changed = progress.ObserveComponents(text, expected, request.Physical);
                    if (changed)
                    {
                        step = progress.ComponentStep;
                        report(new("components", componentMessage + "\n" + PartitionInventory.L("最近完成：", "Last completed: ") + progress.ComponentDetail, progress.Percent));
                    }
                }
                var optionPayload = JsonSerializer.SerializeToNode(request.Options, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower })!;
                if (request.Physical && request.PlannedPartition != null)
                {
                    var repairDisk = PartitionInventory.Read(request.PlannedPartition.Snapshot).Single(d => d.Number == request.PlannedPartition.Disk);
                    optionPayload["_target_disk"] = JsonSerializer.SerializeToNode(new { model = repairDisk.Model, bus = repairDisk.Bus });
                }
                var repairSelection = optionPayload.ToJsonString();
                // Never edit a selected prebuilt image in place.
                var selectedImage = image;
                if (request.Prepared) {
                    selectedImage = Path.Combine(directory, "selected-options.img");
                    await RawImageStaging.ConvertAsync(image, selectedImage, log, token);
                }
                MediaSpace.RequireAvailable(directory, 8ul * 1024 * 1024 * 1024);
                var resultFile = await Backend.GuestAsync("integration", selectedImage, true, ComponentLog, token,
                    selection: repairSelection,
                    secureInput: request.Options.SetDeckPassword ? request.InitialDeckPassword : null);
                await File.WriteAllTextAsync(Path.Combine(directory, "components.log"), resultFile, token);
                var componentResults = resultFile.Split('\n').Select(x => x.Trim()).Where(x => x.StartsWith("OXP_COMPONENT_RESULT=", StringComparison.Ordinal)).Select(x => JsonDocument.Parse(x[21..]).RootElement.Clone()).ToArray();
                await File.WriteAllTextAsync(Path.Combine(directory, "components.json"), JsonSerializer.Serialize(componentResults, new JsonSerializerOptions { WriteIndented = true }), token);
                ComponentOutcome.Validate(componentResults, request.Options);
                if(request.Physical)
                {
                    progress.Advance("components", .88);
                    componentMessage = PartitionInventory.L("正在独立复核 A/B 系统槽的组件…", "Independently verifying components on both system slots…");
                    Phase("components", componentMessage, "02.03");
                    await Backend.GuestAsync("integration-verify",selectedImage,false,ComponentLog,token,
                        selection:repairSelection);
                }
                image = selectedImage;
            }
            progress.Advance("components", 1);
            if (request.Refind != null)
            {
                Phase("bootloader", "正在安装 rEFInd 并保存原启动文件… / Installing rEFInd and preserving the original loader…", "03.01");
                if (request.Options == null && request.Prepared)
                {
                    var copy = Path.Combine(directory, "refind-prepared.img");
                    await RawImageStaging.ConvertAsync(image, copy, log, token);
                    image = copy;
                }
                await RefindInstallation.StageAsync(image,directory,request.Refind,request.PlannedPartition,log,token);
            }
            progress.Advance("bootloader", 1);
            if (request.Physical)
            {
                Phase("preparing", PartitionInventory.L("正在按所选容量调整 SteamOS 数据空间…", "Preparing SteamOS data space for the selected capacity…"), "01.06");
                image = await PreparedCapacity.ExpandAsync(image, directory, request.PlannedPartition!.Capacity, log, token);
            }
            Phase("preparing", PartitionInventory.L("正在检查准备镜像与写入计划…", "Checking the prepared image and write plan…"), "01.07");
            using var prepared = new PreparedDiskImage(image); // Keep the reviewed source immutable across the helper lifetime.
            progress.SetPartitions(prepared.Layout.System.Select(p => (p.Name, p.Size)));
            PhysicalPlan? physical=request.Physical?PhysicalInstallation.Plan(request.PlannedPartition!,request.Kind,prepared.Layout):null;
            if (physical != null) physical = physical with { MakeDefaultBoot = request.MakeDefaultBoot };
            Phase("permission", request.Physical?"即将请求管理员权限，核对并写入已确认的实际磁盘空间。":"即将请求 Windows 管理员权限，用于创建和写入新的虚拟测试盘。", "04.00");
            var nonce = Guid.NewGuid().ToString("N"); var deployment = Path.Combine(Work, "partition-deploy-" + nonce); Directory.CreateDirectory(deployment);
            state = state with { Deployment = deployment }; Save(journal, state);
            var jobPath = Path.Combine(deployment, "partition-job.json");
            await File.WriteAllTextAsync(jobPath, JsonSerializer.Serialize(new PartitionJob(1, nonce, request.Physical?"reviewed-physical-range":"new-virtual-disk-only", request.Kind, prepared.Identity, PhysicalPlan:physical)), token);
            var result = await RunHelperAsync(jobPath, nonce, text =>
            {
                if (state.Stage == "permission") Phase("writing", request.Physical?"正在写入已确认的磁盘空间…":"正在写入虚拟测试盘…", "04.00");
                log(text + Environment.NewLine);
                var pieces = text.Split(':');
                if (text.StartsWith("PARTITION_PROGRESS=", StringComparison.Ordinal) && pieces.Length == 5
                    && long.TryParse(pieces[2], out var written) && long.TryParse(pieces[3], out var verified) && long.TryParse(pieces[4], out var size) && size > 0)
                {
                    progress.ObservePartition(text);
                    step = InstallationProgressTracker.PartitionStep(pieces[0][19..], pieces[1]);
                    report(new("writing", PartitionInventory.L(pieces[1] == "verifying" ? "正在读回核对：" : "正在写入：", pieces[1] == "verifying" ? "Reading back: " : "Writing: ") + pieces[0][19..]));
                }
                else if (text.StartsWith("PARTITION_DEPLOYED=", StringComparison.Ordinal))
                {
                    progress.ObservePartition(text); step = InstallationProgressTracker.PartitionStep(text[19..], "verifying");
                    report(new("writing", PartitionInventory.L("已完成写入与核对：", "Written and verified: ") + text[19..]));
                }
                else if (text == "PARTITION_PHASE=preserving") report(new("writing", "正在准备测试盘布局…"));
                else if (text == "PARTITION_PHASE=registering-boot")
                {
                    step = "04.90";
                    report(new("writing", request.MakeDefaultBoot
                        ? PartitionInventory.L("正在登记并设置默认启动入口…", "Registering and setting the default boot entry…")
                        : PartitionInventory.L("正在登记 SteamOS 启动入口…", "Registering the SteamOS boot entry…")));
                }
            }, token);
            if (result.Status == "cancelled") throw new OperationCanceledException(token);
            if (result.Status != "complete") throw new IOException(result.Error ?? "分区写入未完成。");
            token.ThrowIfCancellationRequested();
            if(request.Physical)
            {
                var desktop = SteamOSDesktop.Install(request.Kind, deployment, log, state.Options?.InstallerLanguage ?? InstallerI18n.Language);
                state = state with { DesktopRebootScript = desktop.Path, DesktopRebootWarning = desktop.Warning };
                state=state with {Status="awaiting-device-boot",Stage="awaiting-device-boot",UpdatedUtc=DateTime.UtcNow}; Save(journal,state);
                report(new("complete","已完成磁盘写入及读回，请通过掌机启动菜单选择 SteamOS，完成首次实机启动验证。",progress.Complete(), "04.99"));
                return state;
            }
            progress.Advance("writing", 1);
            Phase("booting", "分区写入和读回已完成，正在启动独立虚拟机验证 SteamOS…", "05.01");
            await PartitionDeploymentChecks.ProveBootAsync(deployment, request.Kind, log, token, request.Refind?.Timeout == 0);
            state = state with { Status = "complete", Stage = "complete", UpdatedUtc = DateTime.UtcNow }; Save(journal, state);
            report(new("complete", "演练完成：SteamOS 已启动至登录提示。", progress.Complete(), "05.99"));
        }
        catch (Exception error)
        {
            var denied = error is Win32Exception { NativeErrorCode: 1223 };
            state = state with { Status = error is OperationCanceledException || denied ? "cancelled" : "failed", Error = denied ? "管理员权限请求已取消。" : error.Message, UpdatedUtc = DateTime.UtcNow };
            Save(journal, state); log(error.ToString()); report(new(state.Status, state.Error!));
        }
        return state;
    }
    public static string EventName(string nonce) => @"Local\Oxp3Partition-" + nonce;
    private static async Task<PartitionJobResult> RunHelperAsync(string path, string nonce, Action<string> log, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        using var signal = new EventWaitHandle(false, EventResetMode.ManualReset, EventName(nonce));
        using var registration = token.Register(() => signal.Set());
        var admin = new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
        var start = new ProcessStartInfo(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe"))
        { UseShellExecute = !admin, CreateNoWindow = admin, WindowStyle = ProcessWindowStyle.Hidden };
        if (!admin) start.Verb = "runas";
        start.ArgumentList.Add(Path.Combine(Backend.Root, "app/bin/Debug/net10.0-windows/OxpInstaller.dll"));
        start.ArgumentList.Add("--partition-helper"); start.ArgumentList.Add(path);
        using var process = Process.Start(start) ?? throw new IOException("无法启动分区写入助手。");
        var logPath = Path.Combine(Path.GetDirectoryName(path)!, "helper.jsonl"); long offset = 0; string pending = "";
        async Task ReadLog()
        {
            if (!File.Exists(logPath)) return;
            using var file = new FileStream(logPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite); file.Position = offset;
            using var reader = new StreamReader(file); pending += await reader.ReadToEndAsync(); offset = file.Position;
            var lines = pending.Split('\n'); pending = lines[^1];
            foreach (var line in lines[..^1]) if (!string.IsNullOrWhiteSpace(line)) log(JsonSerializer.Deserialize<string>(line)!);
        }
        try
        {
            while (!process.HasExited) { await ReadLog(); await Task.Delay(100); }
            await process.WaitForExitAsync(); await ReadLog();
            var resultPath = Path.Combine(Path.GetDirectoryName(path)!, "helper-result.json");
            if (!File.Exists(resultPath)) throw new IOException("写入助手意外结束。保留任务记录，不能视为完成。");
            var result = JsonSerializer.Deserialize<PartitionJobResult>(await File.ReadAllTextAsync(resultPath)) ?? throw new IOException("缺少写入结果。");
            if ((process.ExitCode == 0) != (result.Status == "complete") || (process.ExitCode == 2) != (result.Status == "cancelled")) throw new IOException("写入结果与进程退出状态不一致。");
            return result;
        }
        finally { if (!process.HasExited) { signal.Set(); await process.WaitForExitAsync(); } }
    }
    public static async Task<int> ExecuteHelperAsync(string path)
    {
        path = Path.GetFullPath(path); MediaSource.Ordinary(path, Work);
        if (Path.GetFileName(path) != "partition-job.json" || new FileInfo(path).Length > 65536) throw new IOException("Invalid partition job path/size.");
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        var job = await JsonSerializer.DeserializeAsync<PartitionJob>(file) ?? throw new IOException("Empty job.");
        if (job.Schema != 1 || job.Scope is not ("new-virtual-disk-only" or "resume-owned-vhd-only" or "reviewed-physical-range") || !Enum.IsDefined(job.Kind) || !Regex.IsMatch(job.Nonce, "^[0-9a-f]{32}$")
            || Path.GetFileName(Path.GetDirectoryName(path)!) != "partition-deploy-" + job.Nonce) throw new IOException("Unsupported deployment job.");
        if ((job.Scope=="reviewed-physical-range") != (job.PhysicalPlan!=null) || job.PhysicalPlan!=null && (job.RecoveryState!=null || job.PhysicalPlan.Kind!=job.Kind)) throw new IOException("Invalid physical installation job.");
        if (job.Scope == "new-virtual-disk-only" && job.RecoveryState != null
            || job.Scope == "resume-owned-vhd-only" && (string.IsNullOrEmpty(job.RecoveryState) || Path.GetFileName(job.RecoveryState) != "state.json"))
            throw new IOException("Unsupported recovery job.");
        if (job.RecoveryState != null) MediaSource.Ordinary(job.RecoveryState, Work);
        using var signal = EventWaitHandle.OpenExisting(EventName(job.Nonce));
        using var cancellation = new CancellationTokenSource();
        if (signal.WaitOne(0)) cancellation.Cancel();
        await using var poll = new Timer(_ => { if (signal.WaitOne(0)) cancellation.Cancel(); }, null, 0, 100);
        var directory = Path.GetDirectoryName(path)!;
        var logPath = Path.Combine(directory, "helper.jsonl"); MediaSource.Ordinary(logPath, Work, false);
        using var writer = new StreamWriter(new FileStream(logPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
        var result = new PartitionJobResult("failed", null);
        try
        {
            if (!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) throw new IOException("Administrator helper required.");
            using var image = new PreparedDiskImage(job.Source.Path);
            if (image.Identity != job.Source) throw new IOException("Prepared image changed after review.");
            cancellation.Token.ThrowIfCancellationRequested();
            Action<string> report = line => { lock (writer) writer.WriteLine(JsonSerializer.Serialize(line)); };
            if(job.PhysicalPlan!=null) await PhysicalInstallation.ApplyAsync(image,job.PhysicalPlan,directory,report,cancellation.Token);
            else if (job.RecoveryState != null)
                await ResumePreparedAsync(image, job.Kind, job.RecoveryState, report, cancellation.Token);
            else await PartitionDeploymentChecks.WritePreparedAsync(job.Source.Path, job.Kind, directory, report, cancellation.Token);
            result = new("complete", null);
        }
        catch (Exception error) { writer.WriteLine(JsonSerializer.Serialize(error.ToString())); result = new(error is OperationCanceledException ? "cancelled" : "failed", error.Message); }
        var resultPath = Path.Combine(directory, "helper-result.json"); MediaSource.Ordinary(resultPath, Work, false);
        using (var output = new FileStream(resultPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        { await JsonSerializer.SerializeAsync(output, result); output.Flush(true); }
        return result.Status == "complete" ? 0 : result.Status == "cancelled" ? 2 : 1;
    }
}



