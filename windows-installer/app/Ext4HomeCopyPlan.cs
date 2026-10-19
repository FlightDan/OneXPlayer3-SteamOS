using System.Buffers.Binary;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OxpInstaller;

public sealed record HomeCopyProfile(string Mode, string Digest)
{
    internal void Validate()
    {
        if (Mode is not ("ext4-used-v1" or "full") || Digest == null || !Regex.IsMatch(Digest, "^[0-9a-f]{64}$"))
            throw new IOException("Unknown or invalid home copy profile.");
    }
}

internal readonly record struct CopyExtent(long Offset, long Length);

// Allocation decisions come from the pinned, read-only Linux filesystem tools.
// Windows only accepts bounded ranges for the exact immutable prepared home.
internal sealed class Ext4HomeCopyPlan
{
    internal const string Selection = "{\"home_copy\":true}";
    private readonly CopyExtent[] ranges;
    internal IReadOnlyList<CopyExtent> Ranges => Array.AsReadOnly(ranges);
    internal long UsedBytes { get; }
    internal HomeCopyProfile Profile { get; }
    private Ext4HomeCopyPlan(CopyExtent[] ranges, long bytes, HomeCopyProfile profile)
        => (this.ranges, UsedBytes, Profile) = (ranges, bytes, profile);

    internal static Ext4HomeCopyPlan FromTranscript(string transcript, PreparedDiskImage image)
    {
        image.Recheck();
        var result = FromTranscript(transcript, image.Stream, image.Layout.System.Single(p => p.Name == "home"));
        image.Recheck();
        return result;
    }

    internal static Ext4HomeCopyPlan FromTranscript(string transcript, FileStream source, PreparedPartition home)
    {
        const string marker = "OXP_HOME_COPY_PLAN=";
        var lines = transcript.Split('\n').Select(s => s.TrimEnd('\r')).Where(s => s.StartsWith(marker, StringComparison.Ordinal)).ToArray();
        if (lines.Length != 1) throw new IOException("Expected one independently generated home copy plan.");
        var json = lines[0][marker.Length..];
        if (Encoding.UTF8.GetByteCount(json) > 1024 * 1024) throw new IOException("Oversized home copy plan.");
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            var required = new HashSet<string>(["schema", "mode", "partition_id", "partition_offset", "partition_size", "fs_uuid", "block_size", "block_count", "used_bytes", "features", "ranges"], StringComparer.Ordinal);
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in root.EnumerateObject())
                if (!seen.Add(property.Name) || !required.Contains(property.Name) && property.Name != "fallback_reason")
                    throw new IOException("Duplicate or unknown home copy plan field.");
            if (!required.IsSubsetOf(seen) || root.GetProperty("schema").GetInt32() != 1)
                throw new IOException("Unsupported home copy plan schema.");
            var mode = root.GetProperty("mode").GetString();
            if (mode is not ("ext4-used-v1" or "full")) throw new IOException("Unsupported home copy mode.");
            if (home.Name != "home" || home.Offset < 1048576 || home.Size < 4096 || home.Offset % 512 != 0 || home.Size % 512 != 0
                || home.Offset > source.Length || home.Size > source.Length - home.Offset
                || root.GetProperty("partition_id").GetString() != home.Id.ToString()
                || root.GetProperty("partition_offset").GetInt64() != home.Offset || root.GetProperty("partition_size").GetInt64() != home.Size)
                throw new IOException("Home copy plan is bound to a different partition.");
            var blockSize = root.GetProperty("block_size").GetInt64();
            var blocks = root.GetProperty("block_count").GetInt64();
            if (blockSize is not (1024 or 2048 or 4096 or 8192 or 16384 or 32768 or 65536) || mode == "ext4-used-v1" && blockSize != 4096
                || blocks <= 0 || blocks > long.MaxValue / blockSize || blocks * blockSize != home.Size)
                throw new IOException("Home copy plan filesystem geometry differs.");
            var features = root.GetProperty("features").EnumerateArray().Select(p => p.GetString() ?? throw new IOException("Invalid filesystem feature.")).ToArray();
            if (features.Length > 128 || features.Any(s => !Regex.IsMatch(s, "^[a-zA-Z0-9_]+$"))
                || !features.SequenceEqual(features.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal)))
                throw new IOException("Invalid or unordered filesystem features.");
            if (root.TryGetProperty("fallback_reason", out var reason)
                && (mode != "full" || reason.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(reason.GetString()) || reason.GetString()!.Length > 1024))
                throw new IOException("Invalid full-copy fallback reason.");

            source.Position = checked(home.Offset + 1024);
            var super = new byte[1024]; source.ReadExactly(super);
            var incompat = BinaryPrimitives.ReadUInt32LittleEndian(super.AsSpan(96));
            var actualBlocks = (ulong)BinaryPrimitives.ReadUInt32LittleEndian(super.AsSpan(4));
            if ((incompat & 0x80) != 0) actualBlocks |= (ulong)BinaryPrimitives.ReadUInt32LittleEndian(super.AsSpan(336)) << 32;
            // ext4 UUID bytes are in RFC order, unlike the default Guid byte-array constructor.
            var actualUuid = new Guid(super.AsSpan(104, 16), bigEndian: true).ToString();
            var logBlock = BinaryPrimitives.ReadUInt32LittleEndian(super.AsSpan(24));
            if (BinaryPrimitives.ReadUInt16LittleEndian(super.AsSpan(56)) != 0xef53 || (incompat & 0x40) == 0
                || logBlock > 6 || (1024L << (int)logBlock) != blockSize || actualBlocks != (ulong)blocks
                || root.GetProperty("fs_uuid").GetString() != actualUuid
                || (BinaryPrimitives.ReadUInt16LittleEndian(super.AsSpan(58)) & 1) == 0 || (incompat & 4) != 0)
                throw new IOException("Prepared home superblock differs from the clean filesystem plan.");

            var values = root.GetProperty("ranges").EnumerateArray().ToArray();
            if (values.Length is < 1 or > 8192) throw new IOException("Invalid home copy range count.");
            var ranges = new CopyExtent[values.Length]; long end = 0, total = 0;
            for (var i = 0; i < values.Length; i++)
            {
                var pair = values[i].EnumerateArray().ToArray();
                if (pair.Length != 2) throw new IOException("Invalid home copy range.");
                var offset = pair[0].GetInt64(); var length = pair[1].GetInt64();
                var alignment = mode == "ext4-used-v1" ? blockSize : 512;
                if (offset < 0 || length <= 0 || offset % alignment != 0 || length % alignment != 0 || offset > home.Size || length > home.Size - offset
                    || i == 0 && offset != 0 || i > 0 && offset <= end)
                    throw new IOException("Home copy ranges overlap, are uncoalesced or exceed the filesystem.");
                ranges[i] = new(offset, length); end = offset + length; total = checked(total + length);
            }
            if (total != root.GetProperty("used_bytes").GetInt64() || ranges[0].Length < 2048
                || mode == "full" && (ranges.Length != 1 || ranges[0] != new CopyExtent(0, home.Size)))
                throw new IOException("Home copy byte accounting differs.");
            var profile = new HomeCopyProfile(mode, Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(json))));
            profile.Validate();
            return new(ranges, total, profile);
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException or OverflowException or KeyNotFoundException)
        { throw new IOException("Invalid home copy plan.", error); }
    }
}
