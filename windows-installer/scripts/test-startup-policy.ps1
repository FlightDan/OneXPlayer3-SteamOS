param([string]$PackageRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
$powershell = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell/v1.0/powershell.exe'
$runtime = Join-Path $PackageRoot 'runtime/dotnet/dotnet.exe'
$app = Join-Path $PackageRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll'
$reportDirectory = Join-Path $PackageRoot ('logs/startup-policy-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$proof = [Collections.Generic.List[string]]::new()

# Read the embedded Win32 resource, without launching or elevating either executable.
if (-not ('StartupManifestReader' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public static class StartupManifestReader {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern IntPtr FindResource(IntPtr module, IntPtr name, IntPtr type);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern IntPtr LoadResource(IntPtr module, IntPtr resource);
    [DllImport("kernel32.dll")] static extern IntPtr LockResource(IntPtr resource);
    [DllImport("kernel32.dll")] static extern uint SizeofResource(IntPtr module, IntPtr resource);
    [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
    public static string Read(string path) {
        var module = LoadLibraryEx(path, IntPtr.Zero, 2);
        if (module == IntPtr.Zero) throw new Win32Exception();
        try {
            var resource = FindResource(module, (IntPtr)1, (IntPtr)24);
            if (resource == IntPtr.Zero) throw new Win32Exception();
            var address = LockResource(LoadResource(module, resource));
            if (address == IntPtr.Zero) throw new Win32Exception();
            var bytes = new byte[SizeofResource(module, resource)];
            Marshal.Copy(address, bytes, 0, bytes.Length);
            return Encoding.UTF8.GetString(bytes).TrimStart('\uFEFF').TrimEnd('\0');
        } finally { FreeLibrary(module); }
    }
}
'@
}
foreach ($relative in 'SteamOSInstaller.exe','app/bin/Debug/net10.0-windows/OxpInstaller.exe') {
    [xml]$manifest = [StartupManifestReader]::Read((Join-Path $PackageRoot $relative))
    $level = $manifest.SelectSingleNode("//*[local-name()='requestedExecutionLevel']")
    if ($level.level -ne 'requireAdministrator' -or $level.uiAccess -ne 'false') { throw "Missing administrator manifest: $relative" }
    $proof.Add("administrator-manifest: $relative")
}

$originalPolicy = $env:PSExecutionPolicyPreference
$policiesBefore = & $powershell -NoProfile -NonInteractive -Command 'Get-ExecutionPolicy -List | ConvertTo-Json -Compress'
if ($LASTEXITCODE -ne 0) { throw 'Cannot read initial execution policies' }
try {
    # Only change this test process environment; child processes inherit Restricted.
    $env:PSExecutionPolicyPreference = 'Restricted'
    $baseline = & $powershell -NoProfile -NonInteractive -File (Join-Path $PackageRoot 'scripts/read-disks.ps1') 2>&1
    $baselineExit = $LASTEXITCODE
    $baseline | Out-File (Join-Path $reportDirectory 'restricted-baseline.txt') -Encoding utf8
    if ($baselineExit -eq 0 -or ($baseline -join "`n") -notmatch 'UnauthorizedAccess|PSSecurityException') { throw 'Did not reproduce the execution-policy failure' }
    $proof.Add('original-call-rejected-under-Restricted')

    $inventoryProcess = Start-Process -FilePath (Join-Path $PackageRoot 'SteamOSInstaller.exe') -ArgumentList '--cli','disk-inventory' -WindowStyle Hidden -Wait -PassThru
    if ($inventoryProcess.ExitCode -ne 0) { throw 'Fixed disk inventory failed; see logs/native-cli-result.txt' }
    $snapshot = Join-Path $reportDirectory 'disks.json'
    $cliResult = Get-Content -LiteralPath (Join-Path $PackageRoot 'logs/native-cli-result.txt') -Raw
    ($cliResult -replace '\s*NATIVE_CLI_RESULT=passed\s*$', '') | Set-Content -LiteralPath $snapshot -Encoding utf8
    $disks = @(Get-Content -LiteralPath $snapshot -Raw | ConvertFrom-Json)
    if ($disks.Count -eq 0 -or $null -eq $disks[0].number) { throw 'No live disk inventory returned' }
    $proof.Add('portable-launcher-live-disk-inventory-with-inherited-Restricted')

    & $runtime $app --cli partition-picker-checks $snapshot
    if ($LASTEXITCODE -ne 0) { throw 'Live inventory / partition picker checks failed' }
    Copy-Item -LiteralPath (Join-Path $PackageRoot 'logs/native-cli-result.txt') -Destination (Join-Path $reportDirectory 'partition-picker.txt')
    $proof.Add('live-inventory-parsed-by-partition-picker')
}
finally { $env:PSExecutionPolicyPreference = $originalPolicy }
$policiesAfter = & $powershell -NoProfile -NonInteractive -Command 'Get-ExecutionPolicy -List | ConvertTo-Json -Compress'
if ($LASTEXITCODE -ne 0 -or ($policiesBefore -join "`n") -cne ($policiesAfter -join "`n")) { throw 'Execution policies changed' }
$proof.Add('execution-policies-unchanged')
@{ passed = $true; checks = $proof.ToArray(); scope = 'Read-only disk inventory, WPF picker checks and embedded manifests. Interactive UAC consent is not exercised.' } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reportDirectory 'result.json') -Encoding utf8
Write-Output "Startup policy checks passed: $reportDirectory"
