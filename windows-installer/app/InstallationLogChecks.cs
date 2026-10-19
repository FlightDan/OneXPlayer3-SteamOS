using System.IO;
using System.Text;

namespace OxpInstaller;

internal static class InstallationLogChecks
{
    internal static async Task<IEnumerable<string>> RunAsync(string proofDirectory)
    {
        Directory.CreateDirectory(proofDirectory);
        var directory = Path.Combine(proofDirectory, "installation-logs");
        Directory.CreateDirectory(directory);
        var events = new List<string>();
        void Require(bool condition, string name)
        {
            if (!condition) throw new IOException(name);
            events.Add(name);
        }

        var secret = "installation-log-secret-fixture-" + Guid.NewGuid().ToString("N");
        var request = new InstallationRequest(InstallationTargetKind.ExternalDisk, "fixture.img", false,
            InitialDeckPassword: secret);
        var forwarded = new StringBuilder();
        var forwardGate = new object();
        using var log = new InstallationLog("install", chunk =>
        {
            lock (forwardGate) forwarded.Append(chunk);
        }, directory);

        var logName = Path.GetFileName(log.LogPath);
        Require(logName.StartsWith("installation-", StringComparison.Ordinal)
            && logName.EndsWith(".log", StringComparison.Ordinal)
            && Path.GetDirectoryName(log.LogPath) == Path.GetFullPath(directory), "creates-installer-adjacent-unique-log");
        var header = ReadLiveText(log.LogPath);
        Require(header.Contains("Started UTC:", StringComparison.Ordinal)
            && header.Contains("Installer version: " + ReleaseInfo.DisplayVersion, StringComparison.Ordinal)
            && header.Contains("Kind: install", StringComparison.Ordinal), "header-records-utc-version-and-kind");

        var progressForwardCount = forwarded.Length;
        log.Progress(new InstallationProgress("writing", "Writing partition", 43.2, "04.11"));
        Require(forwarded.Length == progressForwardCount, "progress-does-not-forward-to-ui-log");

        var largeUtf8 = "FIRST-LINE\n" + new string('x', 90000) + "\n最后一行 / LAST-LINE\n";
        log.Write(largeUtf8);
        log.Write("color:\u001b[31mRED\u001b[0m OSC:\u001b]0;window title\u0007 split:");
        log.Write("before\u001b[31");
        log.Write("mred\u001b[0m after\n");

        var liveContents = ReadLiveText(log.LogPath);
        Require(liveContents.Contains(largeUtf8, StringComparison.Ordinal)
            && liveContents.Contains("最后一行 / LAST-LINE", StringComparison.Ordinal), "captures-complete-large-utf8-content");
        Require(liveContents.Contains("\"stage\":\"writing\"", StringComparison.Ordinal)
            && liveContents.Contains("\"step\":\"04.11\"", StringComparison.Ordinal)
            && liveContents.Contains("\"message\":\"Writing partition\"", StringComparison.Ordinal), "records-stage-step-and-message-progress");
        Require(!liveContents.Contains('\u001b') && !liveContents.Contains("window title", StringComparison.Ordinal)
            && liveContents.Contains("color:RED OSC: split:beforered after\n", StringComparison.Ordinal), "strips-complete-and-split-ansi-sequences");
        Require(forwarded.ToString() == largeUtf8 + "color:RED OSC: split:beforered after\n", "forwards-visible-text-after-file-write");
        Require(!liveContents.Contains(secret, StringComparison.Ordinal), "does-not-serialize-installation-request-secrets");
        GC.KeepAlive(request);

        using (var second = new InstallationLog("resume", _ => { }, directory))
        using (var third = new InstallationLog("physical-resume", _ => { }, directory))
            Require(log.LogPath != second.LogPath && second.LogPath != third.LogPath && log.LogPath != third.LogPath,
                "creates-distinct-files-for-concurrent-log-kinds");

        var concurrentPath = Path.Combine(directory, "concurrent-proof");
        Directory.CreateDirectory(concurrentPath);
        using (var concurrent = new InstallationLog("physical-resume", _ => { }, concurrentPath))
        {
            const int workers = 8;
            const int chunksPerWorker = 80;
            Parallel.For(0, workers, worker =>
                Parallel.For(0, chunksPerWorker, chunk => concurrent.Write($"thread-{worker}-{chunk}\n")));
            var lines = ReadLiveText(concurrent.LogPath).Split('\n')
                .Where(line => line.StartsWith("thread-", StringComparison.Ordinal)).ToHashSet(StringComparer.Ordinal);
            var expected = Enumerable.Range(0, workers)
                .SelectMany(worker => Enumerable.Range(0, chunksPerWorker).Select(chunk => $"thread-{worker}-{chunk}"))
                .ToHashSet(StringComparer.Ordinal);
            Require(lines.SetEquals(expected), "concurrent-chunks-are-complete-and-readable-live");
        }

        var invalidKindRefused = false;
        try { using var invalid = new InstallationLog("../unsafe", _ => { }, directory); }
        catch (ArgumentException) { invalidKindRefused = true; }
        Require(invalidKindRefused, "rejects-unsafe-log-kind");

        var rootLogs = Path.Combine(Backend.Root, "logs");
        Directory.CreateDirectory(rootLogs);
        var existingLogs = Directory.EnumerateFiles(rootLogs, "installation-*.log")
            .Select(Path.GetFullPath).ToHashSet(StringComparer.OrdinalIgnoreCase);
        Directory.CreateDirectory(InstallationController.Work);
        var existingSessions = Directory.GetDirectories(InstallationController.Work, "install-session-*")
            .Select(Path.GetFullPath).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var missingOptionsRefused = false;
        try
        {
            await InstallationController.RunAsync(new InstallationRequest(InstallationTargetKind.InternalShared, "absent.img", false,
                Physical: true), _ => { }, _ => { }, CancellationToken.None);
        }
        catch (IOException error) when (error.Message.Contains("Physical installation options are required", StringComparison.Ordinal))
        { missingOptionsRefused = true; }
        var freshLogs = Directory.EnumerateFiles(rootLogs, "installation-*.log")
            .Select(Path.GetFullPath).Where(path => !existingLogs.Contains(path)).ToArray();
        var freshSessions = Directory.GetDirectories(InstallationController.Work, "install-session-*")
            .Select(Path.GetFullPath).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var failureLogs = freshLogs.Where(path =>
        {
            var contents = File.ReadAllText(path, new UTF8Encoding(false));
            return contents.Contains("Physical installation options are required", StringComparison.Ordinal)
                && contents.Contains("InstallationController.ValidateRequest", StringComparison.Ordinal);
        }).ToArray();
        Require(missingOptionsRefused && freshLogs.Length >= 1 && failureLogs.Length == 1,
            "controller-validation-failure-creates-default-log-with-error-and-stack");
        Require(freshSessions.SetEquals(existingSessions), "controller-validation-failure-creates-no-session-or-physical-operation");

        var helperBefore = Directory.GetFiles(rootLogs, "installation-helper-*.log").ToHashSet(StringComparer.OrdinalIgnoreCase);
        var helperFailed = false;
        try
        {
            await Backend.ProcessAsync(Path.Combine(Backend.Root, "runtime/dotnet/dotnet.exe"),
                [typeof(App).Assembly.Location, "--partition-helper"], _ => { }, CancellationToken.None);
        }
        catch (InvalidOperationException error) when (error.Message.Contains("1")) { helperFailed = true; }
        var helperLogs = Directory.GetFiles(rootLogs, "installation-helper-*.log").Where(path => !helperBefore.Contains(path)).ToArray();
        Require(helperFailed && helperLogs.Length == 1 && File.ReadAllText(helperLogs[0]).Contains("Expected partition job"),
            "helper-startup-failure-persists-original-exception-before-job-or-journal");

        return events;
    }

    private static string ReadLiveText(string path)
    {
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = new StreamReader(input, new UTF8Encoding(false));
        return reader.ReadToEnd();
    }
}
