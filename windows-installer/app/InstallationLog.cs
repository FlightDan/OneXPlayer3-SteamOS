using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;

namespace OxpInstaller;

/// <summary>
/// Captures the text and progress produced by one installation attempt in a
/// durable, installer-adjacent log while forwarding text to the existing UI.
/// </summary>
internal sealed class InstallationLog : IDisposable
{
    private enum EscapeState
    {
        Text,
        Escape,
        EscapeIntermediate,
        Csi,
        Osc,
        OscEscape,
        String,
        StringEscape
    }

    private readonly object gate = new();
    private readonly StreamWriter writer;
    private readonly Action<string> forward;
    private EscapeState escapeState;
    private bool disposed;

    internal InstallationLog(string kind, Action<string> forward, string? directory = null)
    {
        if (kind is not ("install" or "resume" or "physical-resume" or "helper"))
            throw new ArgumentException("Unsupported installation log kind.", nameof(kind));
        this.forward = forward ?? throw new ArgumentNullException(nameof(forward));

        var utcStamp = DateTime.UtcNow.ToString("yyyyMMdd'T'HHmmssfff'Z'", CultureInfo.InvariantCulture);
        var logDirectory = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory ?? Path.Combine(Backend.Root, "logs")));
        LogPath = Path.Combine(logDirectory, $"installation-{kind}-{utcStamp}-{Guid.NewGuid():N}.log");

        StreamWriter? opened = null;
        try
        {
            Directory.CreateDirectory(logDirectory);
            MediaSource.Ordinary(LogPath, logDirectory, false);
            opened = new StreamWriter(new FileStream(LogPath, FileMode.CreateNew, FileAccess.Write,
                FileShare.Read), new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
            opened.WriteLine("OXP installation log");
            opened.WriteLine("Started UTC: " + DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture));
            opened.WriteLine("Installer version: " + ReleaseInfo.DisplayVersion);
            opened.WriteLine("Kind: " + kind);
            opened.WriteLine();
            writer = opened;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            try { opened?.Dispose(); }
            catch (IOException closeError)
            {
                throw new IOException("Could not initialize the installation log at '" + LogPath + "'.",
                    new AggregateException(error, closeError));
            }
            throw new IOException("Could not initialize the installation log at '" + LogPath + "'.", error);
        }
    }

    internal string LogPath { get; }

    internal static async Task<int> CaptureHelperAsync(Func<Task<int>> action)
    {
        using var trace = new InstallationLog("helper", _ => { });
        try
        {
            var code = await action();
            trace.Write($"Helper exit code: {code}\n");
            return code;
        }
        catch (Exception error) { trace.Write(error.ToString() + Environment.NewLine); throw; }
    }

    /// <summary>Writes a text chunk to the live log and forwards its visible form to the UI.</summary>
    internal void Write(string chunk)
    {
        ArgumentNullException.ThrowIfNull(chunk);
        string visible;
        lock (gate)
        {
            ThrowIfDisposed();
            visible = StripTerminalSequences(chunk);
            try { writer.Write(visible); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            { throw new IOException("Could not write the installation log at '" + LogPath + "'.", error); }
        }

        // The callback can update UI state. Keep it outside the file lock so a
        // slow or re-entrant UI callback cannot block other log writers.
        forward(visible);
    }

    /// <summary>Records structured progress without forwarding it to the UI log callback.</summary>
    internal void Progress(InstallationProgress progress)
    {
        ArgumentNullException.ThrowIfNull(progress);
        lock (gate)
        {
            ThrowIfDisposed();
            var record = JsonSerializer.Serialize(new
            {
                type = "progress",
                utc = DateTime.UtcNow,
                stage = progress.Stage,
                step = progress.Step,
                percent = progress.Percent,
                message = progress.Message
            });
            try { writer.WriteLine(record); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            { throw new IOException("Could not write the installation log at '" + LogPath + "'.", error); }
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true;
            try { writer.Dispose(); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            { throw new IOException("Could not close the installation log at '" + LogPath + "'.", error); }
        }
    }

    private void ThrowIfDisposed()
    {
        if (disposed) throw new ObjectDisposedException(nameof(InstallationLog));
    }

    // The parser keeps its state between calls because subprocess output can
    // split an ANSI escape sequence across otherwise unrelated text chunks.
    private string StripTerminalSequences(string chunk)
    {
        var visible = new StringBuilder(chunk.Length);
        foreach (var character in chunk)
        {
            switch (escapeState)
            {
                case EscapeState.Text:
                    if (character == '\u001b') escapeState = EscapeState.Escape;
                    else if (character == '\u009b') escapeState = EscapeState.Csi;
                    else if (character is '\u0090' or '\u0098' or '\u009e' or '\u009f') escapeState = EscapeState.String;
                    else if (character == '\u009d') escapeState = EscapeState.Osc;
                    else if (character == '\u009c') { }
                    else visible.Append(character);
                    break;

                case EscapeState.Escape:
                    if (character == '[') escapeState = EscapeState.Csi;
                    else if (character == ']') escapeState = EscapeState.Osc;
                    else if (character is 'P' or 'X' or '^' or '_') escapeState = EscapeState.String;
                    else if (character is >= '\u0020' and <= '\u002f') escapeState = EscapeState.EscapeIntermediate;
                    else if (character == '\u001b') escapeState = EscapeState.Escape;
                    else escapeState = EscapeState.Text;
                    break;

                case EscapeState.EscapeIntermediate:
                    if (character is >= '\u0030' and <= '\u007e') escapeState = EscapeState.Text;
                    else if (character == '\u001b') escapeState = EscapeState.Escape;
                    break;

                case EscapeState.Csi:
                    if (character is >= '\u0040' and <= '\u007e') escapeState = EscapeState.Text;
                    else if (character == '\u001b') escapeState = EscapeState.Escape;
                    break;

                case EscapeState.Osc:
                    if (character == '\u0007' || character == '\u009c') escapeState = EscapeState.Text;
                    else if (character == '\u001b') escapeState = EscapeState.OscEscape;
                    break;

                case EscapeState.OscEscape:
                    if (character == '\\' || character == '\u009c') escapeState = EscapeState.Text;
                    else if (character == '\u001b') escapeState = EscapeState.OscEscape;
                    else escapeState = EscapeState.Osc;
                    break;

                case EscapeState.String:
                    if (character == '\u009c') escapeState = EscapeState.Text;
                    else if (character == '\u001b') escapeState = EscapeState.StringEscape;
                    break;

                case EscapeState.StringEscape:
                    if (character == '\\' || character == '\u009c') escapeState = EscapeState.Text;
                    else if (character == '\u001b') escapeState = EscapeState.StringEscape;
                    else escapeState = EscapeState.String;
                    break;
            }
        }
        return visible.ToString();
    }
}
