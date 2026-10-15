# Read-only identification for filesystems Windows does not expose through Get-Volume.
# This does not unlock, mount, format, or change GPT attributes.
function Initialize-LinuxStorageProbe {
    if ('OxpLinuxStorageProbe' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class OxpLinuxStorageProbe {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr input, uint inputSize, byte[] output, uint size, out uint returned, IntPtr overlap);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetFilePointerEx(SafeFileHandle h, long distance, out long position, uint method);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool ReadFile(SafeFileHandle h, byte[] data, uint count, out uint read, IntPtr overlap);
    static Guid Id(byte[] data, int offset) { var bytes=new byte[16]; Array.Copy(data,offset,bytes,0,16); return new Guid(bytes); }
    static bool Text(byte[] data, int offset, string text) {
        for(int i=0;i<text.Length;i++) if(data[offset+i]!=(byte)text[i]) return false;
        return true;
    }
    static bool PowerOfTwo(uint value) { return value!=0 && (value & (value-1))==0; }
    // Pure byte parser used by fixture tests. The buffer starts at the partition,
    // not the disk. Offsets follow the kernel ext4 and btrfs on-disk formats.
    // https://docs.kernel.org/filesystems/ext4/super.html
    // https://btrfs.readthedocs.io/en/latest/dev/On-disk-format.html
    public static string Identify(byte[] data, long length) {
        if(data==null || data.Length<131072 || length<data.Length || !BitConverter.IsLittleEndian) return "";
        // Refuse encrypted containers even if stale inner-filesystem magic survives.
        if((Text(data,0,"LUKS") && data[4]==0xba && data[5]==0xbe) || Text(data,3,"-FVE-FS-")) return "";
        int e=1024;
        bool ext=BitConverter.ToUInt16(data,e+0x38)==0xef53;
        bool btrfs=Text(data,65536+0x40,"_BHRfS_M");
        if(ext && btrfs) return ""; // Ambiguous/stale signatures require manual inspection.
        if(ext) {
            uint log=BitConverter.ToUInt32(data,e+0x18), features=BitConverter.ToUInt32(data,e+0x60);
            if(log>6 || (features & 0x40)==0 || BitConverter.ToUInt32(data,e)==0 || Id(data,e+0x68)==Guid.Empty
                || BitConverter.ToUInt32(data,e+0x4c)!=1) return "";
            ulong blocks=BitConverter.ToUInt32(data,e+4);
            if((features & 0x80)!=0) blocks|=(ulong)BitConverter.ToUInt32(data,e+0x150)<<32;
            ulong blockSize=1024UL<<(int)log;
            if(blocks==0 || blocks>(ulong)length/blockSize || BitConverter.ToUInt32(data,e+0x20)==0
                || BitConverter.ToUInt32(data,e+0x28)==0 || BitConverter.ToUInt32(data,e+0x14)!=(log==0?1U:0U)) return "";
            return "ext4";
        }
        if(btrfs) {
            int b=65536;
            uint sector=BitConverter.ToUInt32(data,b+0x90), node=BitConverter.ToUInt32(data,b+0x94);
            ulong total=BitConverter.ToUInt64(data,b+0x70), used=BitConverter.ToUInt64(data,b+0x78);
            // Automatic mounting is limited to single-device filesystems.
            if(Id(data,b+0x20)==Guid.Empty || BitConverter.ToUInt64(data,b+0x30)!=65536
                || BitConverter.ToUInt64(data,b+0x48)==0 || BitConverter.ToUInt64(data,b+0x50)==0
                || BitConverter.ToUInt64(data,b+0x58)==0 || BitConverter.ToUInt64(data,b+0x88)!=1
                || total==0 || total>(ulong)length || used>total
                || !PowerOfTwo(sector) || sector<4096 || sector>65536 || !PowerOfTwo(node) || node<sector || node>65536) return "";
            return "btrfs";
        }
        return "";
    }
    public static bool MatchesLayout(byte[] layout, uint returned, Guid diskId, Guid partId, Guid type, long offset, long length) {
        // Win32 DRIVE_LAYOUT_INFORMATION_EX (8-byte alignment): header 48,
        // PARTITION_INFORMATION_EX 144, GPT union at +32, attributes at +64.
        // https://learn.microsoft.com/windows/win32/api/winioctl/ns-winioctl-drive_layout_information_ex
        // https://learn.microsoft.com/windows/win32/api/winioctl/ns-winioctl-partition_information_ex
        // https://learn.microsoft.com/windows/win32/api/winioctl/ns-winioctl-partition_information_gpt
        if(layout==null || returned<48 || returned>layout.Length || BitConverter.ToUInt32(layout,0)!=1 || Id(layout,8)!=diskId) return false;
        var count=BitConverter.ToUInt32(layout,4);
        if(count>(returned-48)/144) return false;
        int matches=0; bool safe=false;
        for(int i=0;i<count;i++) {
            int at=48+i*144;
            if(Id(layout,at+48)!=partId) continue;
            matches++;
            safe=BitConverter.ToUInt32(layout,at)==1 && layout[at+29]==0 && Id(layout,at+32)==type && BitConverter.ToInt64(layout,at+8)==offset
                && BitConverter.ToInt64(layout,at+16)==length && BitConverter.ToUInt64(layout,at+64)==0;
        }
        return matches==1 && safe;
    }
    public static string Probe(int disk, Guid diskId, Guid partId, Guid type, long offset, long length, int sector) {
        var basic=new Guid("ebd0a0a2-b9e5-4433-87c0-68b6b72699c7");
        var linux=new Guid("0fc63daf-8483-4772-8e79-3d69d8477de4");
        if(disk<0 || diskId==Guid.Empty || partId==Guid.Empty || (type!=basic && type!=linux)
            || offset<1048576 || length<131072 || (sector!=512 && sector!=4096) || offset%sector!=0) return "";
        // GENERIC_READ only; no write access and no mutating IOCTLs.
        using(var handle=CreateFile(@"\\.\PhysicalDrive"+disk,0x80000000,3,IntPtr.Zero,3,0,IntPtr.Zero)) {
            if(handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            var layout=new byte[1024*1024]; uint returned;
            if(!DeviceIoControl(handle,0x70050,IntPtr.Zero,0,layout,(uint)layout.Length,out returned,IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error());
            if(!MatchesLayout(layout,returned,diskId,partId,type,offset,length)) return "";
            long position;
            if(!SetFilePointerEx(handle,offset,out position,0) || position!=offset) throw new Win32Exception(Marshal.GetLastWin32Error());
            var data=new byte[131072]; uint read;
            if(!ReadFile(handle,data,(uint)data.Length,out read,IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error());
            if(read!=data.Length) return "";
            return Identify(data,length);
        }
    }
}
'@
}

function Test-LinuxStorageProbeEligible($Disk, $Partition, $Volume) {
    if ([string]$Disk.PartitionStyle -ne 'GPT' -or [string]$Volume.FileSystemType -notin @('', 'Unknown', 'RAW')) { return $false }
    foreach ($name in @('IsOffline', 'IsReadOnly')) { if ($null -eq $Disk.$name -or $Disk.$name) { return $false } }
    foreach ($name in @('IsBoot', 'IsSystem', 'IsOffline')) { if ($null -eq $Partition.$name -or $Partition.$name) { return $false } }
    if ($Partition.IsReadOnly -eq $true) { return $false }
    $type = [guid]::Empty
    if (-not [guid]::TryParse([string]$Partition.GptType, [ref]$type)) { return $false }
    if ($type -notin @([guid]'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7', [guid]'0FC63DAF-8483-4772-8E79-3D69D8477DE4')) { return $false }
    # Windows synthesizes Hidden/ReadOnly for Linux GPT data. Native attributes
    # are verified on the same read-only handle as the signature, before accepting it.
    if ($type -eq [guid]'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7' -and ($null -eq $Partition.IsHidden -or $Partition.IsHidden)) { return $false }
    return $true
}

function Get-LinuxStorageFilesystem($Disk, $Partition) {
    Initialize-LinuxStorageProbe
    [OxpLinuxStorageProbe]::Probe([int]$Disk.Number,[guid]$Disk.Guid,[guid]$Partition.Guid,[guid]$Partition.GptType,[long]$Partition.Offset,[long]$Partition.Size,[int]$Disk.LogicalSectorSize)
}
