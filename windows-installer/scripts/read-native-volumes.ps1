param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
# Read-only: opens volume metadata handles with desired access 0. No locks,
# dismounts, partition changes or filesystem writes to the inspected volumes.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class OxpVolumeDiagnostics {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr FindFirstVolume(StringBuilder name, uint length);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool FindNextVolume(IntPtr search, StringBuilder name, uint length);
    [DllImport("kernel32.dll")] static extern bool FindVolumeClose(IntPtr search);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool DeviceIoControl(SafeFileHandle handle, uint code, IntPtr input, uint inputLength, byte[] output, uint outputLength, out uint returned, IntPtr overlapped);
    static object Query(SafeFileHandle handle, uint code, bool extents) {
        byte[] data = new byte[65536]; uint returned;
        bool ok = DeviceIoControl(handle, code, IntPtr.Zero, 0, data, (uint)data.Length, out returned, IntPtr.Zero);
        int error = ok ? 0 : Marshal.GetLastWin32Error();
        var result = new Dictionary<string,object> { {"ok",ok}, {"error",error}, {"returned",returned} };
        if (returned > data.Length) { result["invalidLength"] = true; return result; }
        result["hex"] = BitConverter.ToString(data, 0, (int)Math.Min(returned, 512u));
        if (!ok) return result;
        if (!extents && returned >= 12) {
            result["deviceType"] = BitConverter.ToUInt32(data,0);
            result["deviceNumber"] = BitConverter.ToUInt32(data,4);
            result["partitionNumber"] = BitConverter.ToUInt32(data,8);
        }
        if (extents && returned >= 8) {
            uint count = BitConverter.ToUInt32(data,0); result["count"] = count;
            var entries = new List<object>();
            for (int i=0; i<count && 8L+24L*(i+1)<=returned; i++) {
                int at=8+24*i; uint disk=BitConverter.ToUInt32(data,at);
                long offset=BitConverter.ToInt64(data,at+8), size=BitConverter.ToInt64(data,at+16);
                entries.Add(new { disk=disk, offset=offset, size=size,
                    valid=disk<=int.MaxValue && offset>=0 && size>0 && offset<=long.MaxValue-size });
            }
            result["extents"] = entries;
        }
        return result;
    }
    public static object[] Read() {
        var volumes=new List<object>(); var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var name=new StringBuilder(1024); IntPtr search=FindFirstVolume(name,1024);
        if (search==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            while (true) {
                string path=name.ToString();
                if (!seen.Add(path)) throw new InvalidOperationException("Repeated volume");
                var entry=new Dictionary<string,object> { {"path",path} };
                using (var handle=CreateFile(path.TrimEnd('\\'),0,3,IntPtr.Zero,3,0,IntPtr.Zero)) {
                    if (handle.IsInvalid) entry["openError"]=Marshal.GetLastWin32Error();
                    else {
                        entry["storageDevice"]=Query(handle,0x2d1080,false);
                        entry["diskExtents"]=Query(handle,0x560000,true);
                    }
                }
                volumes.Add(entry);
                if (FindNextVolume(search,name,1024)) continue;
                int error=Marshal.GetLastWin32Error(); if(error!=18) throw new Win32Exception(error); break;
            }
        } finally { FindVolumeClose(search); }
        return volumes.ToArray();
    }
}
'@
$result = [ordered]@{
    capturedUtc = [DateTime]::UtcNow.ToString('o')
    process64Bit = [Environment]::Is64BitProcess
    volumes = @([OxpVolumeDiagnostics]::Read())
}
$json = $result | ConvertTo-Json -Depth 12
if ($OutputPath) { [IO.File]::WriteAllText($OutputPath, $json, [Text.UTF8Encoding]::new($false)) }
$json
