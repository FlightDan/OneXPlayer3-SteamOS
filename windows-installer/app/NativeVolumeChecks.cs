using System.Buffers.Binary;
using System.IO;
using System.Text.Json;

namespace OxpInstaller;

public static class NativeVolumeChecks
{
    public static string Run()
    {
        var events = new List<string>();
        byte[] Response(params (uint Disk, long Offset, long Size)[] extents)
        {
            var data = new byte[8 + extents.Length * 24];
            BinaryPrimitives.WriteUInt32LittleEndian(data, (uint)extents.Length);
            for (var i = 0; i < extents.Length; i++)
            {
                var at = 8 + i * 24;
                BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(at), extents[i].Disk);
                // Nonzero padding must never be interpreted as part of DiskNumber.
                data[at + 4] = 0xff;
                BinaryPrimitives.WriteInt64LittleEndian(data.AsSpan(at + 8), extents[i].Offset);
                BinaryPrimitives.WriteInt64LittleEndian(data.AsSpan(at + 16), extents[i].Size);
            }
            return data;
        }
        void Require(bool condition, string name)
        { if (!condition) throw new IOException(name); events.Add(name); }
        void Refuse(byte[] data, string detail, string name)
        {
            try { NativeVolumes.ParseExtents(data); }
            catch (IOException error)
            { Require(error.Message.Contains(detail, StringComparison.Ordinal), name); return; }
            throw new IOException("Accepted invalid native metadata: " + name);
        }
        var single = NativeVolumes.ParseExtents(Response((3, 1023226675200, 981467136)));
        Require(single.SequenceEqual(new[] { new NativeExtent(3, 1023226675200, 981467136) }), "aligned-64-bit-offset-and-length");
        var spanned = NativeVolumes.ParseExtents(Response((3, 1048576, 4096), (7, 2097152, 8192)));
        Require(spanned.SequenceEqual(new[] { new NativeExtent(3, 1048576, 4096), new NativeExtent(7, 2097152, 8192) }), "all-spanned-extents-retained");
        Require(NativeVolumes.ParseExtents(Response((0, 0, 512)))[0].Offset == 0, "zero-start-is-valid");
        Refuse(new byte[7], "bytes=7", "short-header-refused");
        Refuse(Response(), "count=0", "zero-count-refused");
        Refuse(Response((1, 512, 512))[..31], "bytes=31", "truncated-entry-refused");
        var badCount = Response((1, 512, 512)); BinaryPrimitives.WriteUInt32LittleEndian(badCount, uint.MaxValue);
        Refuse(badCount, "count=4294967295", "overflowing-count-refused");
        Refuse(Response((uint.MaxValue, 512, 512)), "disk=4294967295", "invalid-disk-number-reported");
        Refuse(Response((1, -512, 512)), "offset=-512", "negative-offset-reported");
        Refuse(Response((1, 512, 0)), "size=0", "empty-extent-refused");
        Refuse(Response((1, 512, -512)), "size=-512", "negative-length-reported");
        Refuse(Response((1, long.MaxValue - 511, 512)), "Invalid native volume extent bounds", "range-overflow-refused");
        Refuse(Response((1, 512, 512), (2, 1024, -512)), "index=1", "invalid-second-extent-not-ignored");
        Refuse(Response((1, 512, 512), (2, 1024, 0)), "index=1", "empty-second-extent-not-ignored");
        var expected = new NativeVolume("synthetic", [new(1, 512, 512)]);
        var attempts = 0; var validations = 0;
        var recovered = NativeVolumeDiscovery.Wait(() => {
            attempts++;
            if (attempts == 1) { NativeVolumes.ParseExtents(Response((1, 512, 0))); }
            return attempts == 2 ? [] : [expected];
        }, values => values.Length == 1, () => validations++, TimeSpan.FromSeconds(2));
        Require(recovered.Single() == expected && attempts == 3 && validations == 3, "transient-invalid-and-missing-volumes-retried-before-use");
        try {
            NativeVolumeDiscovery.Wait(() => throw new IOException("permanent-invalid-extent"), _ => true, () => {}, TimeSpan.Zero);
            throw new InvalidOperationException("Accepted permanently invalid metadata.");
        } catch (IOException error) { Require(error.InnerException?.Message == "permanent-invalid-extent", "persistent-failure-retains-cause-and-refuses"); }
        attempts = 0;
        try {
            NativeVolumeDiscovery.Wait(() => { attempts++; return [expected]; }, _ => true,
                () => throw new IOException("layout-changed"), TimeSpan.FromSeconds(2));
            throw new InvalidOperationException("Accepted changed layout.");
        } catch (IOException error) { Require(error.Message == "layout-changed" && attempts == 0, "layout-change-is-never-retried"); }
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        try {
            NativeVolumeDiscovery.Wait(() => [expected], _ => true, () => {}, TimeSpan.FromSeconds(2), token: cancelled.Token);
            throw new InvalidOperationException("Ignored cancellation.");
        } catch (OperationCanceledException) { events.Add("cancelled-discovery-refused"); }
        return JsonSerializer.Serialize(new { passed = true, events, scope = "Pure native extent decoding; no disk mutation." }, new JsonSerializerOptions { WriteIndented = true });
    }
}
