using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace OxpInstaller;
public static class Backend
{
    public static string Root { get; } = FindRoot();
    private static string FindRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory != null; directory = directory.Parent)
            if (Directory.Exists(Path.Combine(directory.FullName, "guest"))) return directory.FullName;
        throw new DirectoryNotFoundException("未找到工具的 guest 和 runtime 目录。请保留完整工具目录。");
    }
    public static Task<string> PowerShellAsync(string script, IEnumerable<string> arguments, Action<string> log, CancellationToken token)
    {
        if (Path.GetFileName(script) != script || !script.EndsWith(".ps1", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("Expected a bundled PowerShell script name.", nameof(script));
        // Only this child process uses Bypass; do not change the user's persisted execution policy.
        var executable = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        return ProcessAsync(executable, new[] { "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(Root, "scripts", script) }.Concat(arguments), log, token);
    }
    public static async Task<string> ProcessAsync(string executable, IEnumerable<string> arguments, Action<string> log, CancellationToken token,
        IReadOnlyDictionary<string, string>? environment = null)
    {
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        if (environment != null) foreach (var entry in environment) start.Environment[entry.Key] = entry.Value;
        using var process = new Process { StartInfo = start };
        token.ThrowIfCancellationRequested();
        process.Start();
        void Stop()
        {
            try { if (!process.HasExited) process.Kill(true); }
            catch (InvalidOperationException) { }
        }
        using var registration = token.Register(Stop);
        var output = new StringBuilder();
        async Task ReadAsync(StreamReader reader)
        {
            try
            {
                while (await reader.ReadLineAsync(token) is { } line) { lock (output) output.AppendLine(line); log(line + Environment.NewLine); }
            }
            catch
            {
                // A failed log sink must not leave a writer blocked on a full pipe.
                Stop();
                throw;
            }
        }
        try
        {
            await Task.WhenAll(ReadAsync(process.StandardOutput), ReadAsync(process.StandardError), process.WaitForExitAsync(token));
        }
        finally
        {
            Stop();
            await process.WaitForExitAsync();
        }
        token.ThrowIfCancellationRequested();
        if (process.ExitCode != 0) throw new InvalidOperationException($"进程退出码 {process.ExitCode}：{Path.GetFileName(executable)}\n{output}");
        return output.ToString();
    }
    public static async Task<string> ImportAsync(string input, Action<string> log, CancellationToken token)
    {
        input = Path.GetFullPath(input);
        if (!File.Exists(input)) throw new FileNotFoundException("恢复镜像不存在。", input);
        if (input.EndsWith(".img", StringComparison.OrdinalIgnoreCase)) return input;
        if (!input.EndsWith(".img.bz2", StringComparison.OrdinalIgnoreCase) && !input.EndsWith(".img.zip", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("只支持 .img、.img.bz2、.img.zip。");
        var archive = Path.Combine(Root, "runtime/archive/7z.exe");
        if (!File.Exists(archive)) throw new FileNotFoundException("缺少工具自带的解压程序。", archive);
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "import", Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        // Open only the compression wrapper, not a filesystem inside the recovery image.
        var archiveType = input.EndsWith(".img.zip", StringComparison.OrdinalIgnoreCase) ? "-tzip" : "-tbzip2";
        // List names before extraction: do not allow paths to escape the isolated import folder.
        var listing = await ProcessAsync(archive, ["l", "-slt", archiveType, "--", input], _ => { }, token);
        var entries = listing.Split("----------", 2).Last();
        foreach (Match match in Regex.Matches(entries, @"^Path = (.+)$", RegexOptions.Multiline))
        {
            var entry = match.Groups[1].Value.Trim();
            var target = Path.GetFullPath(Path.Combine(directory, entry));
            if (!target.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("归档含有不安全的文件路径。");
        }
        await ProcessAsync(archive, ["x", archiveType, $"-o{directory}", "-y", "--", input], log, token);
        var images = Directory.GetFiles(directory, "*.img", SearchOption.AllDirectories);
        if (images.Length != 1) throw new InvalidOperationException("归档必须包含一个 .img 镜像。");
        return images[0];
    }
    public static async Task CopyImageAsync(string input, string output, CancellationToken token)
    {
        if (string.Equals(Path.GetFullPath(input), Path.GetFullPath(output), StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("输出不能覆盖源镜像。");
        using var source = new FileStream(input, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024, true);
        using var target = new FileStream(output, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 1024, true);
        await source.CopyToAsync(target, token); await target.FlushAsync(token);
    }
    public static async Task<string> GuestAsync(string task, string? image, bool writable, Action<string> log, CancellationToken token, string? selection = null, string? fixture = null, string? stateDisk = null, string? faultBoundary = null, string? updateRoot = null, string? secureInput = null)
    {
        if (secureInput != null && (task is not ("integration" or "secret-input-check") || string.IsNullOrEmpty(secureInput))) throw new ArgumentException("Secure input is available only for integration or its isolated handshake check.", nameof(secureInput));
        byte[]? secureBytes = null;
        char[]? secureEncoded = null;
        var secureEncodedLength = 0;
        if (fixture != null) fixture = Path.GetFullPath(fixture);
        if (stateDisk != null) stateDisk = Path.GetFullPath(stateDisk);
        if (task is not ("home-copy-plan" or "home-copy-plan-checks" or "secret-input-check" or "resize-prepared" or "capacity-check" or "refind-image" or "physical-readiness" or "upgrade-source" or "integration-delta-check" or "integration-verify" or "integration-check" or "integration" or "smoke" or "inspect" or "build" or "verify" or "partition-test" or "handoff-metadata" or "handoff-binding" or "install-session-test" or "session-intent-interrupt" or "session-intent-recover" or "journal-migration-check" or "ui-installed-check" or "ui-cancelled-check" or "deployment-test" or "deployment-interrupt" or "deployment-recovery" or "firstboot-prepare" or "firstboot-verify" or "ui-bootstrap-seed" or "shared-state-test" or "hdr-test" or "plugin-test" or "refine-preview")) throw new ArgumentException("Unknown task");
        if (task is "integration" or "refind-image" or "resize-prepared" or "capacity-check")
        {
            if (image == null) throw new ArgumentException("Missing independent prepared image.");
            MediaSource.Ordinary(image, InstallerWorkspace.DirectoryPath);
        }
        if (task == "session-intent-interrupt" ? faultBoundary is not ("intent" or "appended") : faultBoundary != null)
            throw new ArgumentException("Unsupported intent fault boundary");
        var requiresStateDisk = task is "ui-bootstrap-seed" or "install-session-test" or "session-intent-interrupt" or "session-intent-recover";
        if (requiresStateDisk != (stateDisk != null)) throw new ArgumentException("This task requires its own persistent staging disk");
        if (writable != (task is "build" or "refine-preview" or "integration" or "upgrade-source" or "refind-image" or "resize-prepared" or "capacity-check")) throw new ArgumentException("Only build tasks can modify an output image");
        if (task == "refine-preview" && (image == null || !Path.GetFullPath(image).StartsWith(Path.Combine(Root, "output") + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("开发预览更新只允许工具工作区内的输出副本。");
        if (image != null && (!File.Exists(image) || !string.Equals(Path.GetExtension(image), ".img", StringComparison.OrdinalIgnoreCase) || Path.GetFullPath(image).StartsWith(@"\\.\", StringComparison.Ordinal))) throw new InvalidOperationException("虚拟机只接收普通 .img 文件。");
        if ((task == "upgrade-source") != (updateRoot != null)) throw new IOException("Upgrade task requires a root partition image.");
        if (updateRoot != null) { MediaSource.Ordinary(updateRoot, InstallerWorkspace.DirectoryPath); MediaSource.Ordinary(image!,InstallerWorkspace.DirectoryPath); }
        var id = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfff") + "-" + task;
        var work = Path.Combine(InstallerWorkspace.DirectoryPath, id); Directory.CreateDirectory(work);
        var payload = Path.Combine(work, "payload"); Directory.CreateDirectory(payload);
        using (var manifest = System.Text.Json.JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(Root, "runtime/payload/packages.json"), token)))
        {
            var destination = Path.Combine(payload, "apks"); Directory.CreateDirectory(destination);
            foreach (var package in manifest.RootElement.EnumerateArray())
            {
                var filename = package.GetProperty("name").GetString() + "-" + package.GetProperty("version").GetString() + ".apk";
                if (Path.GetFileName(filename) != filename) throw new InvalidOperationException("离线包路径无效。");
                File.Copy(Path.Combine(Root, "runtime/payload/apks", filename), Path.Combine(destination, filename), false);
            }
        }
        CopyDirectory(Path.Combine(Root, "guest"), Path.Combine(payload, "tasks"));
        if (task == "integration-verify") CopyDirectory(Path.Combine(Root, "components"), Path.Combine(payload, "components"));
        if (task == "refind-image") CopyDirectory(Path.Combine(Root, "components/refind"), Path.Combine(payload, "refind"));
        if (task is "integration" or "integration-check" or "integration-delta-check")
        {
            CopyDirectory(Path.Combine(Root, "components"), Path.Combine(payload, "components"));
            // Missing optional resources are reported by the component installer.
            // Copy/write errors still propagate: the payload must be trustworthy.
            foreach (var (source, target) in new[] { ("cache/integration", "integration"), ("cache/maintenance", "maintenance"), ("cache/plugins", "plugins"), ("cache/components/waydroid", "waydroid") })
            {
                var from = Path.Combine(Root, source); var to = Path.Combine(payload, target);
                if (Directory.Exists(from)) CopyDirectory(from, to);
                else { Directory.CreateDirectory(to); log($"Optional resource unavailable: {source}\n"); }
            }
        }
        if (task is "build" or "refine-preview")
            CopyDirectory(Path.Combine(Root, "runtime/console"), Path.Combine(payload, "console"));
        if (task is "build" or "refine-preview" or "hdr-test" or "shared-state-test" or "firstboot-prepare")
            CopyDirectory(Path.Combine(Root, "components"), Path.Combine(payload, "components"));
        if (task == "plugin-test")
        {
            CopyDirectory(Path.Combine(Root, "components"), Path.Combine(payload, "components"));
            foreach (var (component, filename) in new[] { ("decky", "PluginLoader"), ("steamgriddb", "steamgriddb-1.8.1.zip"), ("protondb", "protondb-1.3.4.zip") })
            {
                var destination = Path.Combine(payload, "plugins", component); Directory.CreateDirectory(destination);
                File.Copy(Path.Combine(Root, "cache/plugins", component, filename), Path.Combine(destination, filename), false);
            }
        }
        if (selection != null) await File.WriteAllTextAsync(Path.Combine(payload, "selection.json"), selection, token);
        if (faultBoundary != null) await File.WriteAllTextAsync(Path.Combine(payload, "fault-boundary.txt"), faultBoundary, token);
        if (task is "build" or "refine-preview" && selection != null)
        {
            using var choices = System.Text.Json.JsonDocument.Parse(selection);
            if (choices.RootElement.TryGetProperty("resources", out var selectedResources))
            foreach (var resource in selectedResources.EnumerateArray())
            {
                var resourceId = resource.GetString();
                if (resourceId is not ("waydroid" or "oxp3-controls" or "hdr")) throw new InvalidOperationException("不支持此组件资源。");
                var from = Path.Combine(Root, "cache/components", resourceId);
                var to = Path.Combine(payload, "resources", resourceId); Directory.CreateDirectory(to);
                using var profile = System.Text.Json.JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(from, "profile.json"), token));
                var filenames = resourceId == "waydroid"
                    ? new[] { "profile.json", "intel-ibt-kernel-calls.patch", profile.RootElement.GetProperty("archive").GetString()!, profile.RootElement.GetProperty("source_archive").GetString()! }
                    : new[] { "profile.json", profile.RootElement.GetProperty("archive").GetString()! };
                foreach (var name in filenames)
                {
                    if (Path.GetFileName(name) != name) throw new InvalidOperationException("组件资源路径无效。");
                    File.Copy(Path.Combine(from, name), Path.Combine(to, name), false);
                }
            }
        }
        var scratch = Path.Combine(work, "scratch.raw");
        using (var disk = new FileStream(scratch, FileMode.CreateNew)) disk.SetLength(task == "home-copy-plan-checks" ? 4L * 1024 * 1024 * 1024 : task == "integration-check" ? 3L * 1024 * 1024 * 1024 : 256L * 1024 * 1024);
        static string Option(string value) => value.Replace('\\', '/').Replace(",", ",,");
        var arguments = new List<string> { "-accel", "tcg", "-m", "1024", "-smp", "2", "-display", "none", "-monitor", "none", "-serial", "stdio", "-no-reboot", "-nic", "none",
            "-kernel", Path.Combine(Root, "runtime/alpine/boot/vmlinuz-virt"), "-initrd", Path.Combine(Root, "runtime/alpine/boot/initramfs-virt"),
            "-append", "console=ttyS0,115200 modules=loop,squashfs,sd-mod,virtio_pci,virtio_blk,vfat alpine_dev=cdrom:iso9660",
            "-drive", $"file={Option(Path.Combine(Root, "cache/alpine-virt-3.23.6-x86_64.iso"))},format=raw,media=cdrom,readonly=on",
            "-drive", $"file={Option(scratch)},format=raw,if=virtio",
            "-drive", $"file=fat:ro:{Option(payload)},format=raw,if=virtio,readonly=on" };
        if (image != null) arguments.AddRange(["-drive", $"file={Option(Path.GetFullPath(image))},format=raw,if=virtio{(writable ? "" : ",readonly=on")}"]);
        if (task is "partition-test" or "handoff-metadata" or "handoff-binding" or "install-session-test" or "session-intent-interrupt" or "session-intent-recover" or "journal-migration-check" or "ui-installed-check" or "ui-cancelled-check" or "deployment-test" or "deployment-interrupt" or "deployment-recovery" or "firstboot-prepare" or "firstboot-verify" or "ui-bootstrap-seed" or "shared-state-test" or "hdr-test" or "plugin-test")
        {
            if (fixture == null) throw new InvalidOperationException("没有选择本工具创建的虚拟测试盘。");
            VerifyFixture(fixture);
            if (task is "deployment-interrupt" or "deployment-recovery" or "install-session-test" or "session-intent-interrupt" or "session-intent-recover" or "journal-migration-check" or "ui-installed-check" or "ui-cancelled-check")
            {
                using var overlayMarker = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.ChangeExtension(fixture, ".fixture.json")));
                var expectedPurpose = task == "install-session-test" ? "isolated generated-media installation session" : task is "ui-installed-check" or "ui-cancelled-check" ? "isolated boot UI install" : task == "journal-migration-check" ? "isolated journal migration check" : task.StartsWith("session-intent-", StringComparison.Ordinal) ? "isolated pre-ESP intent interruption" : "isolated hard interruption check";
                if (!overlayMarker.RootElement.TryGetProperty("purpose", out var purpose) || purpose.GetString() != expectedPurpose)
                    throw new InvalidOperationException("此验证只允许专门创建的隔离虚拟测试盘。");
            }
            if (task is "partition-test" or "handoff-metadata" or "handoff-binding")
            {
                if (image != null) throw new InvalidOperationException("分区夹具创建任务不应接收系统镜像。");
                var reserved = Path.Combine(work, "reserved.raw");
                using (var file = new FileStream(reserved, FileMode.CreateNew)) file.SetLength(1024 * 1024);
                arguments.AddRange(["-drive", $"file={Option(reserved)},format=raw,if=virtio"]);
            }
            else if (image == null) throw new InvalidOperationException("系统部署验证需要恢复镜像。");
            arguments.AddRange(["-drive", $"file={Option(task is "firstboot-verify" or "ui-installed-check" ? QcowReadOnlyGraph.Filename(fixture) : fixture)},format=qcow2,if=virtio{(task is "firstboot-verify" or "handoff-binding" or "ui-installed-check" or "ui-cancelled-check" ? ",readonly=on" : "")}"]);
            if (stateDisk != null)
            {
                VerifyStateDisk(stateDisk, fixture);
                arguments.AddRange(["-drive", $"file={Option(stateDisk)},format=qcow2,if=virtio"]);
            }
        }
        if(updateRoot != null) arguments.AddRange(["-drive", $"file={Option(Path.GetFullPath(updateRoot))},format=raw,if=virtio,readonly=on"]);
        var qemu = Path.Combine(Root, "runtime/qemu-min/qemu-system-x86_64.exe");
        if (task is "integration" or "integration-check") arguments[arguments.IndexOf("-m") + 1] = "2048";
        var start = new ProcessStartInfo(qemu) { WorkingDirectory = Path.GetDirectoryName(qemu)!, UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = start };
        var taskTimeout = TimeSpan.FromMinutes(task is "home-copy-plan-checks" or "refind-image" or "integration" or "integration-check" or "build" or "install-session-test" or "session-intent-interrupt" or "session-intent-recover" or "deployment-test" or "deployment-interrupt" or "deployment-recovery" or "firstboot-prepare" or "firstboot-verify" or "ui-bootstrap-seed" or "shared-state-test" or "hdr-test" or "plugin-test" ? 20 : 5);
        using var timeout = new CancellationTokenSource(taskTimeout);
        using var combined = CancellationTokenSource.CreateLinkedTokenSource(token, timeout.Token);
        // Open the log before starting QEMU: an unwritable/full log disk must
        // not leave a running guest outside the process cleanup scope.
        var logPath = Path.Combine(Root, "logs", id + ".txt"); Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
        using var liveLog = new StreamWriter(new FileStream(logPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
        combined.Token.ThrowIfCancellationRequested();
        process.Start();
        void StopGuest()
        {
            try { if (!process.HasExited) process.Kill(true); }
            catch (InvalidOperationException) { }
        }
        using var kill = combined.Token.Register(StopGuest);
        var transcript = new StringBuilder(); int phase = 0;
        async Task ReadAsync(StreamReader reader)
        {
            try
            {
                var buffer = new char[4096]; int count;
                while ((count = await reader.ReadAsync(buffer.AsMemory(), combined.Token)) > 0)
                {
                    var chunk = new string(buffer, 0, count); string text;
                    lock (transcript) { transcript.Append(chunk); liveLog.Write(chunk); text = transcript.ToString(); }
                    log(chunk);
                    var terminal = Regex.Replace(text, @"\x1b\[[0-9;?]*[A-Za-z]", "");
                    if (Regex.IsMatch(terminal, @"login:\s*$") && Interlocked.CompareExchange(ref phase, 1, 0) == 0) await process.StandardInput.WriteAsync("root\n");
                    else if (Regex.IsMatch(terminal, @"~\s*#\s*$") && Interlocked.CompareExchange(ref phase, 2, 1) == 1)
                    {
                        // Only the secret file uses 077. Applying it to the task also makes
                        // public runtime directories root-only and breaks the deck session.
                        var command = secureInput == null
                            ? $"( umask 022; mkdir -p /mnt/payload && mount -t vfat -o ro /dev/vdb1 /mnt/payload && sh /mnt/payload/tasks/{task}.sh ); poweroff\n"
                            : $"( umask 022; stty sane -echo || exit 1; printf '\\nOXP_SECRET_INPUT_READY\\n'; IFS= read -r oxp_setup_input || exit 1; ( umask 077; printf '%s' \"$oxp_setup_input\" | tr -d '\\r' | base64 -d > /tmp/oxp-deck-initial-password ) || exit 1; unset oxp_setup_input; ( mkdir -p /mnt/payload && mount -t vfat -o ro /dev/vdb1 /mnt/payload && sh /mnt/payload/tasks/{task}.sh ); task_status=$?; rm -f /tmp/oxp-deck-initial-password; stty echo; exit \"$task_status\" ); poweroff\n";
                        for (var offset = 0; offset < command.Length; offset += 8)
                        {
                            await process.StandardInput.WriteAsync(command.AsMemory(offset, Math.Min(8, command.Length - offset)), combined.Token);
                            await process.StandardInput.FlushAsync(combined.Token);
                            await Task.Delay(25, combined.Token);
                        }
                    }
                    else if (secureInput != null && secureEncoded != null && secureEncodedLength > 0
                        && phase == 2 && Regex.IsMatch(terminal, @"(?:^|[\r\n])OXP_SECRET_INPUT_READY[\r\n]"))
                    {
                        if (Interlocked.CompareExchange(ref phase, 3, 2) == 2)
                        {
                            // QEMU's emulated serial receiver can drop a burst larger
                            // than its FIFO, including the terminating newline.
                            // Pace secrets just like the shell command above.
                            for (var offset = 0; offset < secureEncodedLength; offset += 8)
                            {
                                await process.StandardInput.WriteAsync(secureEncoded.AsMemory(offset, Math.Min(8, secureEncodedLength - offset)), combined.Token);
                                await process.StandardInput.FlushAsync(combined.Token);
                                await Task.Delay(25, combined.Token);
                            }
                            await process.StandardInput.WriteAsync("\n".AsMemory(), combined.Token);
                            await process.StandardInput.FlushAsync(combined.Token);
                            lock (transcript) liveLog.WriteLine("\nOXP_SECRET_INPUT_SENT");
                            Array.Clear(secureEncoded);
                            Array.Clear(secureBytes!);
                            secureEncodedLength = 0;
                        }
                    }
                }
            }
            catch
            {
                StopGuest();
                throw;
            }
        }
        try
        {
            if (secureInput != null)
            {
                secureBytes = Encoding.UTF8.GetBytes(secureInput);
                secureEncoded = new char[checked(((secureBytes.Length + 2) / 3) * 4)];
                if (!Convert.TryToBase64Chars(secureBytes, secureEncoded, out secureEncodedLength))
                    throw new InvalidOperationException("Could not encode secure input.");
            }
            await Task.WhenAll(ReadAsync(process.StandardOutput), ReadAsync(process.StandardError), process.WaitForExitAsync(combined.Token));
            combined.Token.ThrowIfCancellationRequested();
            var result = transcript.ToString();
            if (process.ExitCode != 0 || !Regex.IsMatch(result, @"(?:^|[\r\n])OXP_TASK_RESULT=passed[\r\n]")) throw new InvalidOperationException("构建环境任务失败，参见日志：" + logPath);
            return result;
        }
        catch (OperationCanceledException error) when (timeout.IsCancellationRequested && !token.IsCancellationRequested)
        {
            throw new TimeoutException($"构建环境任务 {task} 超过 {taskTimeout.TotalMinutes:g} 分钟，参见日志：{logPath}", error);
        }
        finally
        {
            if (secureEncoded != null) Array.Clear(secureEncoded);
            if (secureBytes != null) Array.Clear(secureBytes);
            if (!process.HasExited)
            {
                StopGuest();
                await process.WaitForExitAsync();
            }
            await liveLog.FlushAsync();
        }
    }
    private static void CopyDirectory(string from, string to)
    {
        Directory.CreateDirectory(to);
        foreach (var file in Directory.GetFiles(from).Where(file => !file.EndsWith(".pyc", StringComparison.OrdinalIgnoreCase))) File.Copy(file, Path.Combine(to, Path.GetFileName(file)), false);
        foreach (var sub in Directory.GetDirectories(from).Where(sub => Path.GetFileName(sub) != "__pycache__")) CopyDirectory(sub, Path.Combine(to, Path.GetFileName(sub)));
    }
    public static void VerifyFixture(string fixture)
    {
        fixture = Path.GetFullPath(fixture);
        var work = Path.GetFullPath(InstallerWorkspace.DirectoryPath) + Path.DirectorySeparatorChar;
        if (!fixture.StartsWith(work, StringComparison.OrdinalIgnoreCase) || Path.GetFileName(fixture) != "windows-fixture.qcow2" || !File.Exists(fixture))
            throw new InvalidOperationException("只允许本工具创建的工作区虚拟测试盘。");
        var marker = Path.ChangeExtension(fixture, ".fixture.json");
        using var value = System.Text.Json.JsonDocument.Parse(File.ReadAllText(marker));
        if (value.RootElement.GetProperty("kind").GetString() != "oxp3-virtual-fixture" || value.RootElement.GetProperty("size").GetInt64() != 80L * 1024 * 1024 * 1024)
            throw new InvalidOperationException("虚拟盘来源记录不符合本工具测试规格。");
        for (var directory = new DirectoryInfo(Path.GetDirectoryName(fixture)!); directory != null && directory.FullName.StartsWith(work, StringComparison.OrdinalIgnoreCase); directory = directory.Parent)
            if ((directory.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException("虚拟测试路径不能是目录重定向。");
        if ((File.GetAttributes(fixture) & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException("虚拟测试盘不能是文件链接。");
    }
    public static async Task<string> CreateFixtureAsync(Action<string> log, CancellationToken token)
    {
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "virtual-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var fixture = Path.Combine(directory, "windows-fixture.qcow2");
        await ProcessAsync(Path.Combine(Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-f", "qcow2", fixture, "80G"], log, token);
        var marker = System.Text.Json.JsonSerializer.Serialize(new { kind = "oxp3-virtual-fixture", size = 80L * 1024 * 1024 * 1024 });
        await File.WriteAllTextAsync(Path.ChangeExtension(fixture, ".fixture.json"), marker, token);
        await GuestAsync("partition-test", null, false, log, token, fixture: fixture);
        return fixture;
    }

    public static async Task<string> CreateFixtureOverlayAsync(string fixture, Action<string> log, CancellationToken token, string purpose = "isolated hard interruption check")
    {
        VerifyFixture(fixture);
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "virtual-hardstop-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var overlay = Path.Combine(directory, "windows-fixture.qcow2");
        await ProcessAsync(Path.Combine(Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-f", "qcow2", "-F", "qcow2", "-b", Path.GetRelativePath(directory, Path.GetFullPath(fixture)), overlay], log, token);
        await File.WriteAllTextAsync(Path.ChangeExtension(overlay, ".fixture.json"), System.Text.Json.JsonSerializer.Serialize(new
        { kind = "oxp3-virtual-fixture", size = 80L * 1024 * 1024 * 1024, backing = Path.GetFullPath(fixture), purpose }), token);
        return overlay;
    }

    public static async Task<string> CheckHandoffAsync(Action<string> log, CancellationToken token, string? media = null)
    {
        if (media != null)
        {
            if (!File.Exists(media) || !string.Equals(Path.GetExtension(media), ".img", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("请先制作并选择带来源记录的输出介质。");
            if (new DriveInfo(Path.GetPathRoot(InstallerWorkspace.DirectoryPath)!).AvailableFreeSpace < 12L * 1024 * 1024 * 1024)
                throw new InvalidOperationException("介质安装验证至少需要 12 GiB 可用工作空间。");
        }
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, (media == null ? "handoff-" : "install-session-") + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var fixture = Path.Combine(directory, "windows-fixture.qcow2");
        await ProcessAsync(Path.Combine(Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-f", "qcow2", fixture, "80G"], log, token);
        await File.WriteAllTextAsync(Path.ChangeExtension(fixture, ".fixture.json"), System.Text.Json.JsonSerializer.Serialize(new
        { kind = "oxp3-virtual-fixture", size = 80L * 1024 * 1024 * 1024, purpose = media == null ? "Windows/Linux metadata handoff" : "isolated generated-media installation session" }), token);
        var snapshot = await GuestAsync("handoff-metadata", null, false, log, token, fixture: fixture);
        var line = Regex.Match(snapshot, @"(?:^|[\r\n])OXP_HANDOFF_SNAPSHOT=([^\r\n]+)");
        if (!line.Success) throw new InvalidOperationException("未读取到夹具布局。");
        var target = DiskPlanning.FreeSpaces(line.Groups[1].Value).Single();
        var selection = System.Text.Json.JsonSerializer.Serialize(DiskPlanning.Preview(target));
        await File.WriteAllTextAsync(Path.Combine(directory, "windows-selection.json"), selection, token);
        var stateDisk = media == null ? null : await CreateStateDiskAsync(fixture, log, token);
        await GuestAsync(media == null ? "handoff-binding" : "install-session-test", media, false, log, token, selection, fixture, stateDisk);
        await File.WriteAllTextAsync(Path.Combine(directory, "result.json"), System.Text.Json.JsonSerializer.Serialize(new
        { passed = true, fixture, scope = media == null
            ? "Real QEMU GPT metadata -> Windows native planner -> new read-only Linux binding; synthetic Windows snapshot, no Windows OS or physical installation"
            : "Real QEMU GPT -> native Windows plan -> separate Linux confirmation -> append -> generated media A/B deployment with retry, preview layer detachment and public resources; no Windows OS or physical acceptance" }), token);
        return directory;
    }

    private static void VerifyStateDisk(string stateDisk, string fixture)
    {
        VerifyFixture(fixture);
        var expected = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(fixture))!, "session-state.qcow2");
        if (!string.Equals(Path.GetFullPath(stateDisk), expected, StringComparison.OrdinalIgnoreCase) || !File.Exists(stateDisk)
            || (File.GetAttributes(stateDisk) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException("状态盘必须是本次测试盘旁的普通工作区文件。");
        using var marker = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.ChangeExtension(stateDisk, ".state.json")));
        if (marker.RootElement.GetProperty("kind").GetString() != "oxp3-session-state" || marker.RootElement.GetProperty("size").GetInt64() != 16L * 1024 * 1024)
            throw new InvalidOperationException("状态盘来源规格不匹配。");
    }

    internal static async Task<string> CreateStateDiskAsync(string fixture, Action<string> log, CancellationToken token)
    {
        VerifyFixture(fixture);
        var path = Path.Combine(Path.GetDirectoryName(fixture)!, "session-state.qcow2");
        if (File.Exists(path)) throw new InvalidOperationException("状态盘已存在，不覆盖既有安装意图。");
        await ProcessAsync(Path.Combine(Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-f", "qcow2", path, "16M"], log, token);
        await File.WriteAllTextAsync(Path.ChangeExtension(path, ".state.json"), System.Text.Json.JsonSerializer.Serialize(new
        { kind = "oxp3-session-state", size = 16L * 1024 * 1024 }), token);
        return path;
    }

    public static async Task<string> CheckIntentInterruptionAsync(string media, string boundary, Action<string> log, CancellationToken token)
    {
        if (boundary is not ("intent" or "appended")) throw new ArgumentException("Unknown intent boundary");
        var directory = Path.Combine(InstallerWorkspace.DirectoryPath, "intent-stop-" + boundary + "-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(directory);
        var fixture = Path.Combine(directory, "windows-fixture.qcow2");
        await ProcessAsync(Path.Combine(Root, "runtime/qemu-min/qemu-img.exe"), ["create", "-f", "qcow2", fixture, "80G"], log, token);
        await File.WriteAllTextAsync(Path.ChangeExtension(fixture, ".fixture.json"), System.Text.Json.JsonSerializer.Serialize(new
        { kind = "oxp3-virtual-fixture", size = 80L * 1024 * 1024 * 1024, purpose = "isolated pre-ESP intent interruption" }), token);
        var snapshot = await GuestAsync("handoff-metadata", null, false, log, token, fixture: fixture);
        var line = Regex.Match(snapshot, @"(?:^|[\r\n])OXP_HANDOFF_SNAPSHOT=([^\r\n]+)");
        if (!line.Success) throw new InvalidOperationException("未读取到夹具布局。");
        var selection = System.Text.Json.JsonSerializer.Serialize(DiskPlanning.Preview(DiskPlanning.FreeSpaces(line.Groups[1].Value).Single()));
        await File.WriteAllTextAsync(Path.Combine(directory, "windows-selection.json"), selection, token);
        var stateDisk = await CreateStateDiskAsync(fixture, log, token);
        var transcript = new StringBuilder(); var reached = false;
        using var interrupt = CancellationTokenSource.CreateLinkedTokenSource(token);
        try
        {
            await GuestAsync("session-intent-interrupt", media, false, text =>
            {
                log(text);
                lock (transcript)
                {
                    transcript.Append(text);
                    if (!reached && transcript.ToString().Contains("OXP_INSTALL_HARDSTOP=" + boundary + ":intent-durable", StringComparison.Ordinal))
                    { reached = true; interrupt.Cancel(); }
                }
            }, interrupt.Token, selection, fixture, stateDisk, boundary);
            throw new InvalidOperationException("未到达指定的追加意图中断边界。");
        }
        catch (OperationCanceledException) when (reached && !token.IsCancellationRequested)
        { log("已实际终止本次 QEMU；新的 VM 将读取外部状态盘并核对目标，不执行根系统复制。"); }
        token.ThrowIfCancellationRequested();
        await GuestAsync("session-intent-recover", media, false, log, token, selection, fixture, stateDisk);
        await File.WriteAllTextAsync(Path.Combine(directory, "result.json"), System.Text.Json.JsonSerializer.Serialize(new
        { passed = true, reached, boundary, fixture, stateDisk,
          scope = "Real QEMU termination with persistent pre-ESP intent, new Linux VM resume, original Windows EFI/NTFS preservation and ESP journal handoff; no root-system copy, Windows OS or physical acceptance" }), token);
        return directory;
    }
}
