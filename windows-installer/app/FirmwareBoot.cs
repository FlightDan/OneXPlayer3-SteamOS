using System.Buffers.Binary;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace OxpInstaller;

public static class FirmwareBoot
{
    private const string Global="{8BE4DF61-93CA-11D2-AA0D-00E098032B8C}";
    [DllImport("kernel32.dll",SetLastError=true)]private static extern bool GetFirmwareType(out uint type);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]private static extern uint GetFirmwareEnvironmentVariableEx(string name,string guid,byte[] data,uint size,out uint attributes);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]private static extern bool SetFirmwareEnvironmentVariableEx(string name,string guid,byte[] data,uint size,uint attributes);
    [DllImport("kernel32.dll")]private static extern IntPtr GetCurrentProcess();
    [DllImport("advapi32.dll",SetLastError=true)]private static extern bool OpenProcessToken(IntPtr process,uint access,out SafeFileHandle token);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]private static extern bool LookupPrivilegeValue(string? system,string name,out long luid);
    [StructLayout(LayoutKind.Sequential,Pack=4)]private struct Privileges{public uint Count;public long Luid;public uint Attributes;}
    [DllImport("advapi32.dll",SetLastError=true)]private static extern bool AdjustTokenPrivileges(SafeFileHandle token,bool disable,ref Privileges state,uint size,IntPtr previous,IntPtr returned);
    private static void Enable()
    {
        if(!OpenProcessToken(GetCurrentProcess(),0x28,out var token))throw new Win32Exception(Marshal.GetLastWin32Error());
        using(token){if(!LookupPrivilegeValue(null,"SeSystemEnvironmentPrivilege",out var luid))throw new Win32Exception(Marshal.GetLastWin32Error());
            var value=new Privileges{Count=1,Luid=luid,Attributes=2};
            if(!AdjustTokenPrivileges(token,false,ref value,0,IntPtr.Zero,IntPtr.Zero)||Marshal.GetLastWin32Error()!=0)throw new Win32Exception(Marshal.GetLastWin32Error());}
    }
    private static (byte[] Data,uint Attributes)? Read(string name)
    {
        var buffer=new byte[65536];var length=GetFirmwareEnvironmentVariableEx(name,Global,buffer,(uint)buffer.Length,out var attributes);
        if(length==0){var error=Marshal.GetLastWin32Error();if(error==203)return null;throw new Win32Exception(error,"Read firmware "+name);}
        return(buffer[..checked((int)length)],attributes);
    }
    private static void Write(string name,byte[] data,uint attributes)
    {if(!SetFirmwareEnvironmentVariableEx(name,Global,data,(uint)data.Length,attributes))throw new Win32Exception(Marshal.GetLastWin32Error(),"Write firmware "+name);}
    internal static void RequireSecureBootDisabled(byte[]? state)
    {
        if (state == null || state.Length != 1 || state[0] > 1)
            throw new IOException("无法确认安全启动已关闭，请以管理员身份重新检测。 / Could not verify that Secure Boot is disabled. Run as administrator and check again.");
        if (state[0] != 0)
            throw new IOException("检测到安全启动仍已开启。请在 BIOS / UEFI 中关闭 Secure Boot，返回 Windows 后重新检测；现在无法继续安装。 / Secure Boot is still enabled. Disable it in BIOS / UEFI, return to Windows and check again before continuing.");
    }
    public static void RequireSecureBootDisabled()
    {
        if(!GetFirmwareType(out var type)||type!=2)throw new IOException("需要 Windows 以 UEFI 启动才能确认安全启动状态。 / Start Windows in UEFI mode to verify Secure Boot.");
        Enable();var secure=Read("SecureBoot");
        RequireSecureBootDisabled(secure?.Data);
    }
    public static void RequireSupported()
    {
        RequireSecureBootDisabled();
        var order=Read("BootOrder");if(order==null||order.Value.Data.Length%2!=0)throw new IOException("Cannot read firmware boot order.");
    }
    public static byte[] LoadOption(PreparedPartition esp)
    {
        if(esp.Type!=Guid.Parse("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")||esp.Id==Guid.Empty||esp.Offset%512!=0||esp.Size%512!=0||esp.Number<1)throw new IOException("Invalid EFI partition.");
        var description=Encoding.Unicode.GetBytes("SteamOS (OXP3)\0");
        var file=Encoding.Unicode.GetBytes("\\EFI\\BOOT\\BOOTX64.EFI\0");
        var path=new byte[42+4+file.Length+4];path[0]=4;path[1]=1;BinaryPrimitives.WriteUInt16LittleEndian(path.AsSpan(2),42);
        BinaryPrimitives.WriteUInt32LittleEndian(path.AsSpan(4),(uint)esp.Number);
        BinaryPrimitives.WriteUInt64LittleEndian(path.AsSpan(8),(ulong)(esp.Offset/512));BinaryPrimitives.WriteUInt64LittleEndian(path.AsSpan(16),(ulong)(esp.Size/512));
        esp.Id.TryWriteBytes(path.AsSpan(24,16));path[40]=2;path[41]=2;
        path[42]=4;path[43]=4;BinaryPrimitives.WriteUInt16LittleEndian(path.AsSpan(44),(ushort)(4+file.Length));file.CopyTo(path,46);
        path[^4]=0x7f;path[^3]=0xff;path[^2]=4;
        var result=new byte[6+description.Length+path.Length];BinaryPrimitives.WriteUInt32LittleEndian(result,1);BinaryPrimitives.WriteUInt16LittleEndian(result.AsSpan(4),(ushort)path.Length);
        description.CopyTo(result,6);path.CopyTo(result,6+description.Length);return result;
    }
    internal static byte[] RegistrationOrder(byte[] original, ushort chosen, bool makeDefault)
    {
        if (original.Length % 2 != 0 || original.Length > 65532) throw new IOException("Invalid firmware boot order.");
        var after = new byte[original.Length + 2];
        original.CopyTo(after, makeDefault ? 2 : 0);
        BinaryPrimitives.WriteUInt16LittleEndian(after.AsSpan(makeDefault ? 0 : original.Length), chosen);
        return after;
    }
    public static void Register(PreparedPartition esp,string directory,bool makeDefault = false)
    {
        RequireSupported();
        RegisterCore(esp, directory, makeDefault, Read, Write);
    }
    // Dependency injection keeps registration/rollback checks away from real firmware.
    internal static void RegisterCore(PreparedPartition esp, string directory, bool makeDefault,
        Func<string, (byte[] Data, uint Attributes)?> read, Action<string, byte[], uint> write)
    {
        var order=read("BootOrder") ?? throw new IOException("Cannot read firmware boot order.");var entry=LoadOption(esp);
        if (order.Data.Length % 2 != 0) throw new IOException("Invalid firmware boot order.");
        var ordered=Enumerable.Range(0,order.Data.Length/2).Select(i=>BinaryPrimitives.ReadUInt16LittleEndian(order.Data.AsSpan(i*2,2))).ToHashSet();
        ushort chosen=0;
        for(ushort i=0x6000;i<0x7000;i++){if(!ordered.Contains(i) && read("Boot"+i.ToString("X4"))==null){chosen=i;break;}}
        if(chosen==0)throw new IOException("No unused firmware entry available.");
        var name="Boot"+chosen.ToString("X4");var after=RegistrationOrder(order.Data,chosen,makeDefault);
        using(var backup=new FileStream(Path.Combine(directory,"firmware-before.json"),FileMode.CreateNew,FileAccess.Write,FileShare.Read))
        {JsonSerializer.Serialize(backup,new {name,originalBootOrder=Convert.ToBase64String(order.Data),attributes=order.Attributes,entry=Convert.ToBase64String(entry),newBootOrder=Convert.ToBase64String(after),makeDefault});backup.Flush(true);}
        if(read("BootOrder")?.Data.SequenceEqual(order.Data)!=true||read(name)!=null)throw new IOException("Firmware changed before registration.");
        try
        {
            write(name,entry,7);
            if(read(name)?.Data.SequenceEqual(entry)!=true)throw new IOException("Firmware entry readback differs.");
            if(read("BootOrder")?.Data.SequenceEqual(order.Data)!=true)throw new IOException("Boot order changed during registration.");
            write("BootOrder",after,order.Attributes);
            if(read("BootOrder")?.Data.SequenceEqual(after)!=true)throw new IOException("Firmware boot order readback differs.");
        }
        catch
        {
            var current=read("BootOrder");
            if(current!=null && current.Value.Data.SequenceEqual(after))write("BootOrder",order.Data,order.Attributes);
            if(read("BootOrder")?.Data.SequenceEqual(order.Data)==true && read(name)?.Data.SequenceEqual(entry)==true)write(name,[],7);
            throw;
        }
        File.WriteAllText(Path.Combine(directory,"firmware-result.json"),JsonSerializer.Serialize(new {status="registered",name,defaultPreserved=!makeDefault,makeDefault,path="\\EFI\\BOOT\\BOOTX64.EFI"}));
    }
}
