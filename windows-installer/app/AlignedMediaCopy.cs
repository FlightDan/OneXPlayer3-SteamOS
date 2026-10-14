using System.IO;
namespace OxpInstaller;
public sealed record MediaProgress(string Stage, long Written, long Verified, long Total, string? Error = null);
public static class AlignedMediaCopy
{
    public static async Task CopyAndVerifyAsync(FileStream source, FileStream target, long length, long capacity, Action<MediaProgress> report, Func<bool> cancelled)
    {
        if (length <= 0 || length % 512 != 0 || capacity < length) throw new IOException("Unaligned or insufficient media capacity.");
        var input = new byte[4 * 1024 * 1024]; var output = new byte[input.Length];
        long written = 0, verified = 0; source.Position = target.Position = 0;
        try
        {
            while (written < length)
            {
                if (cancelled()) throw new OperationCanceledException("Media copy cancelled.");
                var count = (int)Math.Min(input.Length, length - written);
                await source.ReadExactlyAsync(input.AsMemory(0, count));
                if (cancelled()) throw new OperationCanceledException("Media copy cancelled.");
                await target.WriteAsync(input.AsMemory(0, count)); written += count;
                report(new("writing", written, 0, length));
            }
            target.Flush(true); source.Position = target.Position = 0;
            while (verified < length)
            {
                if (cancelled()) throw new OperationCanceledException("Media readback cancelled.");
                var count = (int)Math.Min(input.Length, length - verified);
                await source.ReadExactlyAsync(input.AsMemory(0, count)); await target.ReadExactlyAsync(output.AsMemory(0, count));
                if (!input.AsSpan(0, count).SequenceEqual(output.AsSpan(0, count))) throw new IOException("Media byte readback differs at " + verified);
                verified += count; report(new("verifying", written, verified, length));
            }
            if (cancelled()) throw new OperationCanceledException("Media readback cancelled.");
        }
        catch (Exception original)
        {
            try { target.Flush(true); }
            catch (Exception flush) { throw new AggregateException("Media operation failed and final flush also failed.", original, flush); }
            throw;
        }
        target.Flush(true);
    }
}
