using System.Buffers.Binary;
using System.IO;
using System.Text;
using System.Text.Json;
namespace OxpInstaller;
// Windows QEMU may concatenate relative backing strings beyond MAX_PATH.
// Resolve each filename independently without rewriting the image or its backing
// references, and provide an explicit read-only graph for verification only.
public static class QcowReadOnlyGraph
{
    public static string Filename(string path)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        object Read(string name, int depth)
        {
            name = Path.GetFullPath(name);
            if (depth > 32 || !seen.Add(name) || name.StartsWith(@"\\", StringComparison.Ordinal) || !File.Exists(name)
                || (File.GetAttributes(name) & FileAttributes.ReparsePoint) != 0) throw new IOException("Invalid/cyclic read-only image backing path.");
            for (var parent = new DirectoryInfo(Path.GetDirectoryName(name)!); parent != null; parent = parent.Parent)
                if ((parent.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Redirected read-only image ancestor.");
            if (Path.GetExtension(name) is not (".qcow2" or ".img")) throw new IOException("Unexpected backing image format/path.");
            var file = new Dictionary<string, object?> { ["driver"] = "file", ["filename"] = name.Replace('\\', '/'), ["read-only"] = true };
            using var input = new FileStream(name, FileMode.Open, FileAccess.Read, FileShare.Read);
            var header = new byte[32]; input.ReadExactly(header);
            if (!header.AsSpan(0, 4).SequenceEqual(new byte[] { 0x51, 0x46, 0x49, 0xfb }))
            {
                if (Path.GetExtension(name) != ".img") throw new IOException("Expected QCOW2 backing header.");
                return new Dictionary<string, object?> { ["driver"] = "raw", ["file"] = file, ["read-only"] = true };
            }
            var version = BinaryPrimitives.ReadUInt32BigEndian(header.AsSpan(4, 4));
            var offset = BinaryPrimitives.ReadUInt64BigEndian(header.AsSpan(8, 8)); var length = BinaryPrimitives.ReadUInt32BigEndian(header.AsSpan(16, 4));
            if (version is not (2 or 3) || length > 4096 || offset > (ulong)input.Length || length > (ulong)input.Length - offset || (length == 0) != (offset == 0))
                throw new IOException("Invalid bounded QCOW2 backing header.");
            object? backing = null;
            if (length != 0)
            {
                input.Position = checked((long)offset); var bytes = new byte[length]; input.ReadExactly(bytes);
                var relative = new UTF8Encoding(false, true).GetString(bytes);
                if (relative.Contains('\0') || relative.StartsWith("json:", StringComparison.OrdinalIgnoreCase) || relative.Contains("://", StringComparison.Ordinal)) throw new IOException("Only ordinary local image backings accepted.");
                var resolved = Path.GetFullPath(Path.IsPathRooted(relative) ? relative : Path.Combine(Path.GetDirectoryName(name)!, relative));
                backing = Read(resolved, depth + 1);
            }
            return new Dictionary<string, object?> { ["driver"] = "qcow2", ["file"] = file, ["backing"] = backing, ["read-only"] = true };
        }
        return "json:" + JsonSerializer.Serialize(Read(path, 0));
    }
}