@echo off
setlocal DisableDelayedExpansion
set "OXP3_STEAMOS_BAT=%~f0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "try { & ([scriptblock]::Create(([regex]::Split([IO.File]::ReadAllText($env:OXP3_STEAMOS_BAT), '(?m)^# OXP3-POWERSHELL\r?$'))[1])) } catch { Write-Host $_; exit 1 }"
set "OXP3_EXIT=%errorlevel%"
if not "%OXP3_EXIT%"=="0" pause
exit /b %OXP3_EXIT%
# OXP3-POWERSHELL
$ErrorActionPreference = 'Stop'

# Dependencies are injected only by isolated tests; the desktop entry uses native APIs below.
function Invoke-SteamOSRestart($Name, $Expected, $Read, $Write, $Confirm, $Restart) {
    function Same($a, $b) {
        if ($null -eq $a -or $null -eq $b) { return ($null -eq $a -and $null -eq $b) }
        return $a.Attributes -eq $b.Attributes -and [Convert]::ToBase64String($a.Data) -ceq [Convert]::ToBase64String($b.Data)
    }
    if ($Name -eq '') {
        if (& $Confirm $true) { & $Restart $true }
        return
    }
    $target = & $Read $Name
    if ($null -eq $target -or [Convert]::ToBase64String($target.Data) -cne $Expected) {
        throw 'SteamOS boot entry is missing or changed. Reinstall the desktop script with the installer.'
    }
    if (!(& $Confirm $false)) { return }
    if (!(Same $target (& $Read $Name))) { throw 'SteamOS boot entry changed before restart.' }
    $before = & $Read 'BootNext'
    if ($null -ne $before -and $before.Data.Length -ne 2) { throw 'Invalid existing BootNext.' }
    $next = [pscustomobject]@{ Data = [BitConverter]::GetBytes([Convert]::ToUInt16($Name.Substring(4), 16)); Attributes = [uint32]7 }
    if (!(Same $before (& $Read 'BootNext'))) { throw 'BootNext changed before restart.' }
    try {
        & $Write 'BootNext' $next
        if (!(Same $next (& $Read 'BootNext'))) { throw 'BootNext readback differs; restart cancelled.' }
        & $Restart $false
    } catch {
        $failure = $_
        try {
            if (Same $next (& $Read 'BootNext')) {
                & $Write 'BootNext' $before
                if (!(Same $before (& $Read 'BootNext'))) { throw 'BootNext restore readback differs.' }
            }
        } catch { throw ($failure.ToString() + ' BootNext restoration failed: ' + $_.ToString()) }
        throw $failure
    }
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (!$admin) {
    # Encode the path as data so spaces, quotes, Unicode and shell metacharacters are safe.
    $path64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($env:OXP3_STEAMOS_BAT))
    $command = '$env:OXP3_STEAMOS_BAT=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String(''' + $path64 + ''')); & ([scriptblock]::Create(([regex]::Split([IO.File]::ReadAllText($env:OXP3_STEAMOS_BAT), ''(?m)^# OXP3-POWERSHELL\r?$''))[1]))'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    try {
        $child = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList @('-NoProfile', '-EncodedCommand', $encoded) -Verb RunAs -Wait -PassThru
        exit $child.ExitCode
    } catch { Write-Host $_; exit 1 }
}

try {
    Add-Type -AssemblyName System.Windows.Forms
    $name = '@@BOOT_NAME@@'
    if ($name -ne '') {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class OxpDesktopFirmware {
    const string Global = "{8BE4DF61-93CA-11D2-AA0D-00E098032B8C}";
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr p, uint access, out IntPtr token);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool LookupPrivilegeValue(string system, string name, out long luid);
    [StructLayout(LayoutKind.Sequential, Pack=4)] struct Privileges { public uint Count; public long Luid; public uint Attributes; }
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr token, bool disable, ref Privileges state, uint size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFirmwareEnvironmentVariableEx(string name, string guid, byte[] data, uint size, out uint attributes);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetFirmwareEnvironmentVariableEx(string name, string guid, byte[] data, uint size, uint attributes);
    public sealed class Variable { public byte[] Data; public uint Attributes; }
    public static void Enable() {
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), 0x28, out token)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            long luid;
            if (!LookupPrivilegeValue(null, "SeSystemEnvironmentPrivilege", out luid)) throw new Win32Exception(Marshal.GetLastWin32Error());
            var state = new Privileges { Count=1, Luid=luid, Attributes=2 };
            if (!AdjustTokenPrivileges(token, false, ref state, 0, IntPtr.Zero, IntPtr.Zero) || Marshal.GetLastWin32Error()!=0) throw new Win32Exception(Marshal.GetLastWin32Error());
        } finally { CloseHandle(token); }
    }
    public static Variable Read(string name) {
        var data = new byte[65536]; uint attributes;
        var length = GetFirmwareEnvironmentVariableEx(name, Global, data, (uint)data.Length, out attributes);
        if (length==0) { int error=Marshal.GetLastWin32Error(); if(error==203) return null; throw new Win32Exception(error, "Read " + name); }
        Array.Resize(ref data, (int)length); return new Variable { Data=data, Attributes=attributes };
    }
    public static void Write(string name, byte[] data, uint attributes) {
        if(name!="BootNext") throw new InvalidOperationException("Only BootNext may be written.");
        if (!SetFirmwareEnvironmentVariableEx(name, Global, data, (uint)data.Length, attributes)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Write " + name);
    }
}
'@
        [OxpDesktopFirmware]::Enable()
    }
    Invoke-SteamOSRestart $name '@@BOOT_ENTRY@@' { param($key) [OxpDesktopFirmware]::Read($key) } {
        param($key, $value)
        if ($null -eq $value) { [OxpDesktopFirmware]::Write($key, [byte[]]@(), 7) }
        else { [OxpDesktopFirmware]::Write($key, $value.Data, $value.Attributes) }
    } {
        param($external)
        $text = if ($external) { '请先保存工作。即将重启到 UEFI 设置，请手动选择外部 SteamOS 安装盘。继续？ / Save your work. Restart into UEFI settings and select the external SteamOS disk?' }
                else { '请先保存工作。即将重启到 SteamOS；安装了 rEFInd 时先进入其菜单。继续？ / Save your work. Restart to SteamOS / rEFInd now?' }
        [Windows.Forms.MessageBox]::Show($text, '重启到 SteamOS / Restart to SteamOS', 'YesNo', 'Question', 'Button2') -eq 'Yes'
    } {
        param($external)
        $arguments = if ($external) { @('/r', '/fw', '/t', '0') } else { @('/r', '/t', '0') }
        & "$env:SystemRoot\System32\shutdown.exe" @arguments
        if ($LASTEXITCODE -ne 0) { throw "Restart command failed (exit code $LASTEXITCODE)." }
    }
} catch {
    Write-Host $_ -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
