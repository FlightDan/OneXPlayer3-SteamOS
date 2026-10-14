using System.ComponentModel;
using System.Diagnostics;
using System.IO;

namespace OxpInstaller;

internal static class NativeVolumeDiscovery
{
    // Windows publishes volume devices asynchronously after a GPT update.
    // A retry must obtain a complete, valid snapshot; never omit a bad extent.
    internal static NativeVolume[] Wait(Func<NativeVolume[]> discover, Func<NativeVolume[], bool> ready,
        Action validateTarget, TimeSpan timeout, Action<string>? log = null, CancellationToken token = default)
    {
        var elapsed = Stopwatch.StartNew();
        Exception? last = null;
        var attempts = 0;
        while (true)
        {
            token.ThrowIfCancellationRequested();
            validateTarget(); // Identity/layout changes must fail immediately, outside the retry catch.
            attempts++;
            try
            {
                var volumes = discover();
                if (ready(volumes))
                {
                    if (attempts > 1) log?.Invoke($"PHYSICAL_VOLUME_DISCOVERY=ready; attempts={attempts}");
                    return volumes;
                }
                last = new IOException("New target volumes did not all appear.");
            }
            catch (Exception error) when (error is IOException or Win32Exception) { last = error; }
            if (attempts == 1) log?.Invoke("PHYSICAL_VOLUME_DISCOVERY=waiting; " + last.Message);
            if (elapsed.Elapsed >= timeout)
                throw new IOException("Target volumes did not become valid before the discovery deadline: " + last.Message, last);
            if (token.WaitHandle.WaitOne(100)) token.ThrowIfCancellationRequested();
        }
    }
}
