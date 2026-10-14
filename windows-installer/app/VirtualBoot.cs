using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OxpInstaller;
public static class VirtualBoot
{
    public static async Task<string> RefindImageAsync(string image, bool windowsProbe, bool manual, Action<string> log, CancellationToken token)
    {
        image=Path.GetFullPath(image); MediaSource.Ordinary(image,InstallationController.Work);
        using var prepared=new PreparedDiskImage(image);
        if(prepared.Layout.Size!=InstallationController.Capacity) throw new IOException("Expected an independent prepared image.");
        return await BootAsync(image,"raw",false,log,token,refindManual:manual,windowsProbe:windowsProbe);
    }
    internal static async Task<string> PhysicalAdapterAsync(string path, Action<string> log, CancellationToken token)
    {
        path=Path.GetFullPath(path);MediaSource.Ordinary(path,InstallationController.Work);
        if(Path.GetFileName(path)!="media.vhd" || !Regex.IsMatch(Path.GetFileName(Path.GetDirectoryName(path)!),"^physical-adapter-check-[0-9a-f]{32}$")
            || !File.Exists(path+".owner.json") || !File.Exists(Path.Combine(Path.GetDirectoryName(path)!,"plan.json")))throw new IOException("Missing owned adapter proof.");
        return await BootAsync(path,"vpc",false,log,token);
    }
    public static async Task<string> IntegratedImageAsync(string image, Action<string> log, CancellationToken token)
    {
        image = Path.GetFullPath(image); MediaSource.Ordinary(image, InstallationController.Work);
        using var prepared = new PreparedDiskImage(image);
        if (prepared.Layout.Size != InstallationController.Capacity) throw new IOException("Expected an owned 80 GiB integrated image.");
        return await BootAsync(image, "raw", false, log, token);
    }
    public static async Task<string> RunAsync(string fixture, Action<string> log, CancellationToken token)
    {
        Backend.VerifyFixture(fixture);
        return await BootAsync(Path.GetFullPath(fixture), "qcow2", false, log, token);
    }
    public static async Task<string> PreviewAsync(string image, Action<string> log, CancellationToken token)
    {
        image = Path.GetFullPath(image);
        if (!File.Exists(image) || !image.EndsWith(".img", StringComparison.OrdinalIgnoreCase) || image.StartsWith(@"\\.\", StringComparison.Ordinal))
            throw new InvalidOperationException("只允许普通 .img 镜像文件。");
        return await BootAsync(image, "raw", true, log, token);
    }
    public static async Task<string> WrittenVhdAsync(string path, Action<string> log, CancellationToken token)
    {
        path = Path.GetFullPath(path); MediaSource.Ordinary(path, InstallerWorkspace.DirectoryPath);
        if (Path.GetFileName(path) != "media.vhd") throw new IOException("Expected an owned written VHD.");
        var directory = Path.GetDirectoryName(path)!;
        using var job = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(directory, "media-job.json"), token));
        var result = JsonSerializer.Deserialize<MediaResult>(await File.ReadAllTextAsync(Path.Combine(directory, "result.json"), token));
        var nonce = job.RootElement.GetProperty("Nonce").GetString();
        if (job.RootElement.GetProperty("Schema").GetInt32() != 1 || job.RootElement.GetProperty("Kind").GetString() != "virtual-media-validation"
            || Path.GetFileName(directory) != "media-" + nonce || result == null || result.Status != "complete" || !result.Detached
            || result.Written != result.Total || result.Verified != result.Total || result.Vhd != path)
            throw new IOException("VHD has no successful independent writer result.");
        return await BootAsync(path, "vpc", true, log, token);
    }
    public static async Task<string> PartitionVhdAsync(string path, Action<string> log, CancellationToken token, bool refindManual = false)
    {
        path = Path.GetFullPath(path); MediaSource.Ordinary(path, InstallerWorkspace.DirectoryPath);
        var directory = Path.GetDirectoryName(path)!;
        if (Path.GetFileName(path) != "media.vhd" || !System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(directory), "^partition-deploy-[0-9a-f]{32}$"))
            throw new IOException("Expected an isolated partition-deployed VHD.");
        using var proof = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(directory, "result.json"), token));
        using var state = JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(directory, "state.json"), token));
        var result = proof.RootElement; var stage = state.RootElement;
        if (!result.GetProperty("passed").GetBoolean() || !result.GetProperty("detached").GetBoolean() || result.GetProperty("path").GetString() != path
            || stage.GetProperty("status").GetString() != "complete" || stage.GetProperty("completed").GetArrayLength() != 8
            || stage.GetProperty("target_vhd").GetString() != path || stage.GetProperty("kind").GetString() != result.GetProperty("kind").GetString())
            throw new IOException("Partition VHD lacks a completed detached native deployment proof.");
        return await BootAsync(path, "vpc", false, log, token, refindManual:refindManual);
    }

    public static async Task<string> UiAsync(string image, string baseline, bool install, Action<string> log, CancellationToken token, bool resume = false, bool cancel = false)
    {
        Backend.VerifyFixture(baseline);
        image = Path.GetFullPath(image); baseline = Path.GetFullPath(baseline);
        if (!File.Exists(image) || !image.EndsWith(".img", StringComparison.OrdinalIgnoreCase)
            || !image.StartsWith(Path.Combine(Backend.Root, "output") + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("交互验证只允许本工具工作区的介质副本。");
        return await BootAsync(image, "raw", true, log, token, baseline, install, resume, cancel);
    }
    private static async Task<string> BootAsync(string fixture, string format, bool preview, Action<string> log, CancellationToken token, string? uiBaseline = null, bool uiInstall = false, bool uiResume = false, bool uiCancel = false, bool refindManual = false, bool windowsProbe = false)
    {
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "uefi-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var runtime = Path.Combine(Backend.Root, "runtime/qemu-min");
        var overlay = Path.Combine(directory, "boot.qcow2");
        await Backend.ProcessAsync(Path.Combine(runtime, "qemu-img.exe"), ["create", "-f", "qcow2", "-F", format, "-b", Path.GetRelativePath(directory, fixture), overlay], log, token);
        string? target = null, state = null, contextDirectory = null;
        if (uiBaseline != null)
        {
            target = Path.Combine(directory, "windows-fixture.qcow2");
            await Backend.ProcessAsync(Path.Combine(runtime, "qemu-img.exe"), ["create", "-f", "qcow2", "-F", "qcow2", "-b", Path.GetRelativePath(directory, uiBaseline), target], log, token);
            await File.WriteAllTextAsync(Path.ChangeExtension(target, ".fixture.json"), JsonSerializer.Serialize(new
            { kind = "oxp3-virtual-fixture", size = 80L * 1024 * 1024 * 1024, purpose = "isolated boot UI install" }), token);
            var priorState = Path.Combine(Path.GetDirectoryName(uiBaseline)!, "session-state.qcow2");
            var stateMarkerPath = Path.ChangeExtension(priorState, ".state.json");
            if (File.Exists(stateMarkerPath))
            {
                using var stateMarker = JsonDocument.Parse(await File.ReadAllTextAsync(stateMarkerPath, token));
                if (stateMarker.RootElement.GetProperty("kind").GetString() != "oxp3-session-state"
                    || stateMarker.RootElement.GetProperty("size").GetInt64() != 16L * 1024 * 1024)
                    throw new InvalidOperationException("测试状态盘来源不匹配。");
            }
            else throw new InvalidOperationException("测试状态盘来源记录缺失；恢复操作也必须核对来源。");
            if ((File.GetAttributes(priorState) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("测试状态盘来源不匹配。");
            state = Path.Combine(directory, "session-state.qcow2");
            await Backend.ProcessAsync(Path.Combine(runtime, "qemu-img.exe"), ["create", "-f", "qcow2", "-F", "qcow2", "-b", Path.GetRelativePath(directory, priorState), state], log, token);
            await File.WriteAllTextAsync(Path.ChangeExtension(state, ".state.json"), JsonSerializer.Serialize(new { kind = "oxp3-session-state", size = 16L * 1024 * 1024 }), token);
            contextDirectory = Path.Combine(directory, "ui-context"); Directory.CreateDirectory(contextDirectory);
            var baselineDirectory = Path.GetDirectoryName(uiBaseline)!;
            var selectionPath = Path.Combine(baselineDirectory, "windows-selection.json");
            using var selection = JsonDocument.Parse(await File.ReadAllTextAsync(File.Exists(selectionPath) ? selectionPath : Path.Combine(baselineDirectory, "ui-context/context.json"), token));
            var choice = File.Exists(selectionPath) ? selection.RootElement : selection.RootElement.GetProperty("selection");
            await File.WriteAllTextAsync(Path.Combine(contextDirectory, "context.json"), JsonSerializer.Serialize(new
            { schema = 1, kind = "oxp3-isolated-ui-install", selection = choice }), token);
        }
        var variables = Path.Combine(directory, "vars.fd");
        File.Copy(Path.Combine(runtime, "share/edk2-i386-vars.fd"), variables, false);
        var serialPath = Path.Combine(directory, "serial.txt");
        var screenPath = Path.Combine(directory, "screen.png");
        static string Option(string path) => path.Replace('\\', '/').Replace(",", ",,");
        var start = new ProcessStartInfo(Path.Combine(runtime, "qemu-system-x86_64.exe"))
        {
            WorkingDirectory = runtime, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true
        };
        var arguments = new List<string> { "-accel", "tcg", "-machine", "q35", "-m", "2048", "-smp", "2", "-display", "none", "-monitor", "none", "-nic", "none", "-no-reboot",
            "-vga", "none", "-device", "virtio-gpu-pci",
            "-serial", "file:" + Option(serialPath), "-qmp", "stdio",
            "-drive", $"if=pflash,format=raw,readonly=on,file={Option(Path.Combine(runtime, "share/edk2-x86_64-code.fd"))}",
            "-drive", $"if=pflash,format=raw,file={Option(variables)}",
            "-drive", $"file={Option(overlay)},format=qcow2,if=none,id=bootdisk", "-device", "nvme,drive=bootdisk,serial=OXP3-TEST-BOOT" };
        if (uiBaseline != null)
        {
            arguments.AddRange(["-device", "pcie-root-port,id=source-port,chassis=7,slot=7",
                "-drive", $"file=fat:ro:{Option(contextDirectory!)},format=raw,readonly=on,if=none,id=uicontext",
                "-device", "virtio-blk-pci,drive=uicontext,serial=OXP3-UI-CONTEXT",
                "-drive", $"file={Option(target!)},format=qcow2,if=none,id=installtarget", "-device", "virtio-blk-pci,drive=installtarget,serial=OXP3-LAB-TARGET",
                "-drive", $"file={Option(state!)},format=qcow2,if=none,id=installstate", "-device", "virtio-blk-pci,drive=installstate,serial=OXP3-LAB-STATE"]);
        }
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = start };
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(uiInstall ? 20 : 6));
        using var combined = CancellationTokenSource.CreateLinkedTokenSource(token, timeout.Token);
        var protocol = new StringBuilder();
        var ready = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var finalScreen = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var replies = new Dictionary<string, TaskCompletionSource>();
        using var writerLock = new SemaphoreSlim(1, 1);
        async Task SendAsync(object command)
        {
            await writerLock.WaitAsync(combined.Token);
            try { await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(command).AsMemory(), combined.Token); await process.StandardInput.FlushAsync(combined.Token); }
            finally { writerLock.Release(); }
        }
        process.Start();
        void Stop() { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } }
        using var kill = combined.Token.Register(Stop);
        async Task ReadProtocolAsync()
        {
            while (await process.StandardOutput.ReadLineAsync() is { } line)
            {
                lock (protocol) protocol.AppendLine(line);
                using var message = JsonDocument.Parse(line);
                if (message.RootElement.TryGetProperty("QMP", out _)) await SendAsync(new { execute = "qmp_capabilities", id = "capabilities" });
                else if (message.RootElement.TryGetProperty("id", out var id) && id.GetString() == "capabilities")
                {
                    if (message.RootElement.TryGetProperty("error", out _)) throw new InvalidOperationException("QEMU 控制接口初始化失败。");
                    ready.TrySetResult();
                }
                else if (message.RootElement.TryGetProperty("id", out var screenId))
                {
                    var replyId = screenId.GetString()!;
                    if (replyId == "final-screen") finalScreen.TrySetResult();
                    lock (replies)
                    {
                        if (replies.TryGetValue(replyId, out var completion))
                        {
                            if (message.RootElement.TryGetProperty("error", out var error)) completion.TrySetException(new InvalidOperationException(error.ToString()));
                            else completion.TrySetResult();
                        }
                    }
                }
            }
        }
        async Task ReadErrorsAsync()
        {
            while (await process.StandardError.ReadLineAsync() is { } line) { lock (protocol) protocol.AppendLine(line); log(line); }
        }
        var readers = Task.WhenAll(ReadProtocolAsync(), ReadErrorsAsync());
        bool passed = false; string? failure = null;
        try
        {
            async Task<string> SerialAsync()
            {
                if (!File.Exists(serialPath)) return "";
                await using var stream = new FileStream(serialPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                using var reader = new StreamReader(stream); return await reader.ReadToEndAsync(combined.Token);
            }
            async Task CommandAsync(object command, string id)
            {
                var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                lock (replies) replies.Add(id, completion);
                try { await SendAsync(command); await completion.Task.WaitAsync(TimeSpan.FromSeconds(10), combined.Token); }
                finally { lock (replies) replies.Remove(id); }
            }
            async Task CaptureAsync(string name)
            {
                await Task.Delay(300, combined.Token);
                var id = "capture-" + name;
                await CommandAsync(new { execute = "screendump", arguments = new { filename = Path.Combine(directory, name + ".png"), format = "png" }, id }, id);
            }
            async Task KeyAsync(string key, string page, string step)
            {
                var offset = (await SerialAsync()).Length;
                var id = "key-" + step;
                await CommandAsync(new { execute = "send-key", arguments = new { keys = new[] { new { type = "qcode", data = key } } }, id }, id);
                while (!process.HasExited)
                {
                    combined.Token.ThrowIfCancellationRequested();
                    var current = await SerialAsync();
                    if (current.Length > offset && current[offset..].Contains("OXP_UI_STATE=" + page, StringComparison.Ordinal)) return;
                    if (readers.IsFaulted) await readers;
                    await Task.Delay(200, combined.Token);
                }
                throw new InvalidOperationException("交互页面未到达：" + page);
            }
            log("从临时副本执行 UEFI 启动；测试盘作为只读后备文件。软件模拟启动通常需要几分钟。");
            var nextScreen = Stopwatch.StartNew();
            var bootTime = Stopwatch.StartNew(); bool sourceAttached = false;
            bool refindConfirmed = false;
            while (!process.HasExited)
            {
                combined.Token.ThrowIfCancellationRequested();
                if (readers.IsFaulted) await readers;
                if (File.Exists(serialPath))
                {
                    await using var stream = new FileStream(serialPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                    using var reader = new StreamReader(stream);
                    var serial = await reader.ReadToEndAsync(combined.Token);
                    if (uiBaseline != null && !sourceAttached && serial.Contains("OXP_UI_WAITING_SOURCE", StringComparison.Ordinal))
                    {
                        await ready.Task.WaitAsync(combined.Token);
                        await CommandAsync(new { execute = "blockdev-add", arguments = new Dictionary<string, object>
                            { ["driver"] = "file", ["node-name"] = "ui-source-file", ["filename"] = fixture, ["read-only"] = true }, id = "source-file" }, "source-file");
                        await CommandAsync(new { execute = "blockdev-add", arguments = new Dictionary<string, object>
                            { ["driver"] = "raw", ["node-name"] = "ui-source", ["file"] = "ui-source-file", ["read-only"] = true }, id = "source-raw" }, "source-raw");
                        await CommandAsync(new { execute = "device_add", arguments = new { driver = "virtio-blk-pci", drive = "ui-source", bus = "source-port", id = "ui-source-device", serial = "OXP3-LAB-SOURCE" }, id = "source-device" }, "source-device");
                        sourceAttached = true;
                    }
                    if (windowsProbe ? serial.Contains("PROBE_WINDOWS") : preview ? serial.Contains("OXP_PREVIEW_READY") : Regex.IsMatch(serial, @"SteamOS[^\r\n]*\(ttyS0\)"))
                    {
                        if(refindManual && !refindConfirmed) throw new IOException("Expected manual selection; OS started before confirmation.");
                        passed = true; break;
                    }
                }
                if (refindManual && !refindConfirmed && bootTime.Elapsed > TimeSpan.FromSeconds(25) && ready.Task.IsCompletedSuccessfully)
                {
                    await CaptureAsync("refind-waiting");
                    await CommandAsync(new { execute="send-key",arguments=new { keys=new[] { new { type="qcode",data="ret" } } },id="refind-enter" },"refind-enter");
                    refindConfirmed=true;
                }
                if (bootTime.Elapsed > TimeSpan.FromMinutes(6)) throw new TimeoutException("启动界面未在六分钟内就绪：" + serialPath);
                if (ready.Task.IsCompletedSuccessfully && nextScreen.Elapsed >= TimeSpan.FromSeconds(15))
                {
                    await SendAsync(new { execute = "screendump", arguments = new { filename = screenPath, format = "png" } });
                    nextScreen.Restart();
                }
                await Task.Delay(1000, combined.Token);
            }
            if (!passed) throw new InvalidOperationException("未观察到 SteamOS " + (preview ? "预览服务" : "登录提示") + "；请查看串口日志。");
            if (uiBaseline != null)
            {
                passed = false; await ready.Task.WaitAsync(combined.Token);
                await CaptureAsync("ui-home");
                if (!uiResume)
                {
                    await KeyAsync("1", "review", "review-1"); await CaptureAsync("ui-review");
                    await KeyAsync("b", "home", "back-1");
                    await KeyAsync("3", "resources", "resources"); await CaptureAsync("ui-resources");
                    await KeyAsync("b", "home", "back-2");
                    await KeyAsync("2", "home", "empty-recovery"); await CaptureAsync("ui-recovery-empty");
                }
                if (uiInstall)
                {
                    await KeyAsync(uiResume ? "2" : "1", uiResume ? "resume" : "review", "review-install");
                    await CaptureAsync(uiResume ? "ui-resume" : "ui-confirm");
                    await KeyAsync("i", "progress", "confirm-install");
                    var progressScreen = Stopwatch.StartNew();
                    var cancellationSent = false;
                    while (!process.HasExited)
                    {
                        combined.Token.ThrowIfCancellationRequested();
                        var current = await SerialAsync();
                        if (uiCancel && !cancellationSent && current.Contains("OXP_DEPLOY_PHASE=copy-rootfs-A", StringComparison.Ordinal))
                        {
                            await KeyAsync("c", "home", "cancel-copy-A"); cancellationSent = true;
                            if (!(await SerialAsync()).Contains("OXP_UI_CANCEL_CLEANUP=worker-exited-owned-mounts-cleared", StringComparison.Ordinal))
                                throw new InvalidOperationException("取消后未观察到工作进程挂载清理完成。");
                            await CaptureAsync("ui-cancelled"); break;
                        }
                        if (current.Contains("OXP_UI_STATE=result", StringComparison.Ordinal)) break;
                        if (current.LastIndexOf("OXP_UI_STATE=home", StringComparison.Ordinal) > current.LastIndexOf("OXP_UI_STATE=progress", StringComparison.Ordinal))
                        { await CaptureAsync("ui-failed"); throw new InvalidOperationException("界面安装返回错误；参见串口工作进程日志及 ui-failed.png。"); }
                        if (progressScreen.Elapsed > TimeSpan.FromSeconds(20))
                        { await CaptureAsync("ui-progress"); progressScreen.Restart(); }
                        if (readers.IsFaulted) await readers;
                        await Task.Delay(1000, combined.Token);
                    }
                    if (uiCancel)
                    {
                        if (!cancellationSent) throw new InvalidOperationException("未到达根复制取消边界。");
                    }
                    else
                    {
                        if (!(await SerialAsync()).Contains("OXP_UI_STATE=result", StringComparison.Ordinal)) throw new InvalidOperationException("未完成界面安装。");
                        await CaptureAsync("ui-installed");
                    }
                }
                passed = true;
            }
            if (ready.Task.IsCompletedSuccessfully)
            {
                await SendAsync(new { execute = "screendump", arguments = new { filename = screenPath, format = "png" }, id = "final-screen" });
                try { await finalScreen.Task.WaitAsync(TimeSpan.FromSeconds(5), combined.Token); }
                catch (TimeoutException) { log("截图保存未及时完成；启动结果以串口登录提示为准。"); }
            }
            log(windowsProbe ? "rEFInd 已按 GPT GUID 链式进入 Windows EFI 测试入口；这不是 Windows 操作系统启动验证。" : preview ? "UEFI 引导已执行真实 SteamOS 预览服务。" : "UEFI 引导已进入真实 SteamOS 登录提示。此结果尚未覆盖 Windows 启动、Steam 前端或掌机硬件。");
            return directory;
        }
        catch (OperationCanceledException) when (!token.IsCancellationRequested)
        {
            failure = "UEFI 启动超时";
            throw new TimeoutException(failure + "：" + serialPath);
        }
        catch (Exception error) { failure = error.Message; throw; }
        finally
        {
            Stop(); await process.WaitForExitAsync();
            try { await readers; } catch (Exception error) { lock (protocol) protocol.AppendLine(error.Message); }
            await File.WriteAllTextAsync(Path.Combine(directory, "qmp.txt"), protocol.ToString());
            await File.WriteAllTextAsync(Path.Combine(directory, "result.json"), JsonSerializer.Serialize(new
            {
                passed, failure, refindManual, windowsProbe, cancelled = token.IsCancellationRequested, timedOut = timeout.IsCancellationRequested,
                scope = windowsProbe ? "rEFInd GPT-bound Windows EFI probe, not Windows OS boot" : uiBaseline != null ? (uiCancel ? "Real C-key cancellation during root-A copy; worker cleanup and return to recovery menu; isolated overlays, no full installation or physical acceptance"
                    : uiInstall ? "Real SteamOS boot UI key events through review/resources/recovery and separate install confirmation; isolated target/state overlays, no Windows OS or physical acceptance" : "Real SteamOS boot UI key events through review/resources/empty recovery and back; no install confirmation, isolated overlays")
                    : preview ? "UEFI preview service in an image overlay; visible framebuffer requires inspection" : "UEFI SteamOS fixture boot to serial login; no Windows OS, Steam frontend or hardware acceptance", fixture,
                uiBaseline, target, state, uiResume, uiCancel
            }, new JsonSerializerOptions { WriteIndented = true }));
            log("启动验证记录：" + directory);
        }
    }
}
