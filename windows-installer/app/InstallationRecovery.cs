using System.ComponentModel;
using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public static partial class InstallationController
{
    private static FileStream LeaseSession(string directory)
    {
        var path = Path.Combine(directory, "operation.lock"); MediaSource.Ordinary(path, Work, false);
        return new(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.DeleteOnClose);
    }
    private static string RecoveryState(InstallationSession session)
    {
        if (session.Schema != 1 || !Regex.IsMatch(session.Id, "^[0-9a-f]{32}$") || !Enum.IsDefined(session.Kind)
            || session.Deployment == null || session.Status == "complete") throw new IOException("此任务不能继续恢复。");
        var directory = Path.GetFullPath(session.Deployment);
        if (!Regex.IsMatch(Path.GetFileName(directory), "^partition-deploy-[0-9a-f]{32}$"))
            throw new IOException("恢复目标目录不匹配。");
        var state = Path.Combine(directory, "state.json"); MediaSource.Ordinary(state, Work);
        return state;
    }
    private static MediaSource RecoverySource(InstallationSession session)
    {
        var path = RecoveryState(session);
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length > 65536) throw new IOException("恢复记录过大。");
        using var json = JsonDocument.Parse(file); var state = json.RootElement;
        if (state.GetProperty("schema").GetInt32() != 2 || state.GetProperty("kind").GetString() != session.Kind.ToString()
            || state.GetProperty("target_vhd").GetString() != Path.Combine(session.Deployment!, "media.vhd"))
            throw new IOException("此任务缺少新版本恢复记录，需重新演练。");
        MediaSource.Ordinary(Path.Combine(session.Deployment!, "media.vhd.owner.json"), Work);
        return state.GetProperty("source").Deserialize<MediaSource>() ?? throw new IOException("恢复镜像记录缺失。");
    }
    public static bool CanResume(InstallationSession? session)
    {
        try
        {
            if (session == null) return false;
            var source = RecoverySource(session);
            MediaSource.Ordinary(source.Path, Work);
            return !File.Exists(Path.Combine(SessionDirectory(session), "operation.lock"));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or KeyNotFoundException or InvalidOperationException or ArgumentException)
        { return false; }
    }
    public static async Task ResumePreparedAsync(PreparedDiskImage image, InstallationTargetKind kind, string statePath,
        Action<string> log, CancellationToken token)
    {
        if (image.Layout.Size != Capacity) throw new IOException("恢复演练需要 80 GiB 系统镜像。");
        await PartitionDeployment.ResumeOwnedAsync(image, kind, statePath, log, token);
        // ResumeOwnedAsync has returned only after disposing and detaching its VHD.
        var directory = Path.GetDirectoryName(statePath)!;
        var resultPath = Path.Combine(directory, "result.json"); MediaSource.Ordinary(resultPath, Work, false);
        MediaSource.Ordinary(resultPath + ".tmp", Work, false);
        if (File.Exists(resultPath))
            File.Copy(resultPath, resultPath + ".before-resume-" + Guid.NewGuid().ToString("N") + ".json", false);
        using (var output = new FileStream(resultPath + ".tmp", FileMode.Create, FileAccess.Write, FileShare.None))
        {
            JsonSerializer.Serialize(output, new { passed = true, kind = kind.ToString(), path = Path.Combine(directory, "media.vhd"),
                imagePath = image.Identity.Path, detached = true,
                scope = "Owned VHD resumed after completed-prefix byte comparison; no physical disk or host boot acceptance" });
            output.Flush(true);
        }
        File.Move(resultPath + ".tmp", resultPath, true);
    }
    public static async Task<InstallationSession> ResumeAsync(InstallationSession selected, Action<InstallationProgress> report,
        Action<string> log, CancellationToken token)
        => await WithInstallationLogAsync("resume", log, trace => ResumeCoreAsync(selected,
            update => { trace.Progress(update); report(update); }, trace.Write, token));

    private static async Task<InstallationSession> ResumeCoreAsync(InstallationSession selected, Action<InstallationProgress> report,
        Action<string> log, CancellationToken token)
    {
        _ = RecoveryState(selected);
        var directory = SessionDirectory(selected); var journal = Path.Combine(directory, "session.json");
        MediaSource.Ordinary(journal, Work);
        using var lease = LeaseSession(directory);
        var state = JsonSerializer.Deserialize<InstallationSession>(File.ReadAllText(journal)) ?? throw new IOException("任务记录缺失。");
        if (state.Id != selected.Id || state.Kind != selected.Kind || state.Deployment != selected.Deployment
            || state.Source != selected.Source || state.Status == "complete") throw new IOException("任务状态已变化，请重新打开安装助手。");
        var source = RecoverySource(state); var recovery = RecoveryState(state);
        token.ThrowIfCancellationRequested();
        using var image = new PreparedDiskImage(source.Path);
        if (image.Identity != source || image.Layout.Size != Capacity) throw new IOException("恢复所需的系统镜像已变化。");
        var free = new DriveInfo(Path.GetPathRoot(state.Deployment!)!).AvailableFreeSpace;
        if (free < Capacity + 512L * 1024 * 1024) throw new IOException("继续演练需至少 80.5 GiB 可用空间。");
        File.Copy(journal, Path.Combine(directory, "session.before-resume-" + Guid.NewGuid().ToString("N") + ".json"), false);
        var progress = new InstallationProgressTracker();
        progress.Advance("bootloader", 1);
        progress.SetPartitions(image.Layout.System.Select(p => (p.Name, p.Size)));
        using var progressLog = new StreamWriter(new FileStream(Path.Combine(directory, "progress-resume-" + Guid.NewGuid().ToString("N") + ".jsonl"), FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
        var publish = report; var step = "04.00";
        report = value =>
        {
            value = value with { Percent = value.Percent ?? progress.Percent, Step = value.Step ?? step };
            progressLog.WriteLine(JsonSerializer.Serialize(new { utc = DateTime.UtcNow, value.Stage, value.Step, value.Percent, value.Message }));
            publish(value);
        };
        state = state with { Status = "running", Stage = "permission", Error = null, UpdatedUtc = DateTime.UtcNow }; Save(journal, state);
        void Phase(string stage, string message)
        { state = state with { Stage = stage, UpdatedUtc = DateTime.UtcNow }; Save(journal, state); report(new(stage, message)); }
        try
        {
            Phase("permission", "即将请求管理员权限，复查并继续上次虚拟盘演练。");
            var nonce = Guid.NewGuid().ToString("N");
            var attempt = Path.Combine(Work, "partition-deploy-" + nonce); Directory.CreateDirectory(attempt);
            var job = Path.Combine(attempt, "partition-job.json");
            await File.WriteAllTextAsync(job, JsonSerializer.Serialize(new PartitionJob(1, nonce, "resume-owned-vhd-only", state.Kind, source, recovery)), token);
            log("RECOVERY_ATTEMPT=" + attempt + Environment.NewLine);
            var result = await RunHelperAsync(job, nonce, text =>
            {
                if (state.Stage == "permission") Phase("writing", "正在复查上次写入的内容…");
                log(text + Environment.NewLine);
                if (text.StartsWith("PARTITION_RECHECKING="))
                {
                    step = InstallationProgressTracker.PartitionStep(text[20..], "verifying");
                    report(new("writing", PartitionInventory.L("正在复查已完成分区：", "Rechecking completed partition: ") + text[20..]));
                }
                else if (text.StartsWith("PARTITION_RECHECKED="))
                {
                    progress.ObservePartition(text); step = InstallationProgressTracker.PartitionStep(text[20..], "verifying");
                    report(new("writing", "已复查，无需重写：" + text[20..]));
                }
                else if (text.StartsWith("PARTITION_DEPLOYED="))
                {
                    progress.ObservePartition(text); step = InstallationProgressTracker.PartitionStep(text[19..], "verifying");
                    report(new("writing", "已续写并核对：" + text[19..]));
                }
                else if (text.StartsWith("PARTITION_PROGRESS="))
                {
                    var pieces = text.Split(':');
                    if (pieces.Length == 5 && long.TryParse(pieces[2], out var written) && long.TryParse(pieces[3], out var verified)
                        && long.TryParse(pieces[4], out var size) && size > 0)
                    {
                        progress.ObservePartition(text); step = InstallationProgressTracker.PartitionStep(pieces[0][19..], pieces[1]);
                        report(new("writing", "正在续写并核对：" + pieces[0][19..]));
                    }
                }
            }, token);
            if (result.Status == "cancelled") throw new OperationCanceledException(token);
            if (result.Status != "complete") throw new IOException(result.Error ?? "恢复写入未完成。");
            token.ThrowIfCancellationRequested();
            progress.Advance("writing", 1); step = "05.01";
            Phase("booting", "系统内容已恢复完成，正在重新验证 SteamOS 启动…");
            await PartitionDeploymentChecks.ProveBootAsync(state.Deployment!, state.Kind, log, token, state.Refind?.Timeout == 0);
            state = state with { Status = "complete", Stage = "complete", UpdatedUtc = DateTime.UtcNow }; Save(journal, state);
            report(new("complete", "恢复演练完成：SteamOS 已启动至登录提示。", progress.Complete(), "05.99"));
        }
        catch (Exception error)
        {
            var denied = error is Win32Exception { NativeErrorCode: 1223 };
            state = state with { Status = error is OperationCanceledException || denied ? "cancelled" : "failed",
                Error = denied ? "管理员权限请求已取消。" : error.Message, UpdatedUtc = DateTime.UtcNow };
            Save(journal, state); log(error.ToString()); report(new(state.Status, state.Error!));
        }
        return state;
    }
}
