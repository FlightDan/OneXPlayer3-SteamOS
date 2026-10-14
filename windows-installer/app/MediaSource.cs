using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;
public sealed record MediaSource(string Path, long Length, long WriteTime, uint Volume, ulong FileId, Guid DiskGuid)
{
    [StructLayout(LayoutKind.Sequential)] private struct FileTime { public uint Low, High; }
    [StructLayout(LayoutKind.Sequential)] private struct FileInformation
    {
        public uint Attributes; public FileTime Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInformation information);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetFinalPathNameByHandle(SafeFileHandle handle, StringBuilder path, uint length, uint flags);
    public static void Ordinary(string path, string scope, bool exists = true)
    {
        path = System.IO.Path.GetFullPath(path); scope = System.IO.Path.GetFullPath(scope);
        if (!path.StartsWith(scope + System.IO.Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Path is outside the tool workspace.");
        if (exists && !File.Exists(path)) throw new IOException("Expected an ordinary existing file.");
        if ((File.Exists(path) || Directory.Exists(path)) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("Redirected workspace file.");
        for (var dir = new DirectoryInfo(System.IO.Path.GetDirectoryName(path)!); dir != null; dir = dir.Parent)
            if (dir.Exists && (dir.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Redirected workspace path.");
    }
    public static MediaSource Read(string path)
    {
        using var file = Open(path); return FromHandle(path, file);
    }
    public static FileStream Open(string path)
    {
        path = System.IO.Path.GetFullPath(path);
        Ordinary(path, System.IO.Path.Combine(Backend.Root, "output"));
        if (!path.EndsWith(".img", StringComparison.OrdinalIgnoreCase)) throw new IOException("Only a prepared .img is accepted.");
        var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024, FileOptions.SequentialScan);
        try
        {
            var actual = new StringBuilder(4096); var count = GetFinalPathNameByHandle(file.SafeFileHandle, actual, 4096, 0);
            if (count == 0 || count >= 4096) throw new Win32Exception(Marshal.GetLastWin32Error(), "Read source handle path");
            var final = actual.ToString(); if (final.StartsWith(@"\\?\", StringComparison.Ordinal)) final = final[4..];
            if (!string.Equals(final, path, StringComparison.OrdinalIgnoreCase)) throw new IOException("Source handle path differs from the reviewed image.");
            return file;
        }
        catch { file.Dispose(); throw; }
    }
    public static MediaSource FromHandle(string path, FileStream file)
    {
        if (!GetFileInformationByHandle(file.SafeFileHandle, out var info)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Read source file identity");
        var length = ((long)info.SizeHigh << 32) | info.SizeLow;
        if (length < 16 * 1024 * 1024 || length % 512 != 0) throw new IOException("Source image size is not sector aligned.");
        file.Position = 0; var header = new byte[1024]; file.ReadExactly(header); file.Position = 0;
        if (header[510] != 0x55 || header[511] != 0xAA || Encoding.ASCII.GetString(header, 512, 8) != "EFI PART"
            || BitConverter.ToUInt32(header, 524) < 92 || BitConverter.ToUInt32(header, 524) > 512
            || BitConverter.ToUInt64(header, 536) != 1 || BitConverter.ToUInt64(header, 544) >= (ulong)(length / 512))
            throw new IOException("Expected a bounded 512-sector GPT image.");
        var guid = new Guid(header.AsSpan(568, 16)); if (guid == Guid.Empty) throw new IOException("Source GPT identifier is missing.");
        return new MediaSource(System.IO.Path.GetFullPath(path), length, ((long)info.Write.High << 32) | info.Write.Low,
            info.Volume, ((ulong)info.IndexHigh << 32) | info.IndexLow, guid);
    }
}

