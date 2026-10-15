param([string]$ProjectRoot=(Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference='Stop'
$ProjectRoot=[IO.Path]::GetFullPath($ProjectRoot)
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$reportRoot=Join-Path $ProjectRoot ('logs/release-smoke-'+$stamp)
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$checks=[Collections.Generic.List[string]]::new()
$release=Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/release.json') -Raw | ConvertFrom-Json
$launcher=Join-Path $ProjectRoot 'SteamOSInstaller.exe'
$data=[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($launcher))
if (!$data.Contains('app/bin/Debug/net10.0-windows/OxpInstaller.dll') -or !$data.Contains('../../../../runtime/dotnet')) {
    throw 'Root launcher does not bind the packaged DLL/runtime.'
}
$binary=(Get-Item -LiteralPath (Join-Path $ProjectRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll')).VersionInfo.FileVersion
if ($binary -ne (($release.version -replace '-beta$','')+'.0')) { throw 'Release and binary versions differ.' }
$checks.Add('version-and-portable-launcher-binding')
function Invoke-LauncherCheck([string[]]$Arguments,[string]$Result,[string]$Name,[switch]$Cli) {
    $resultPath=Join-Path $ProjectRoot $Result
    $started=Get-Date
    $process=Start-Process -FilePath $launcher -ArgumentList $Arguments -WorkingDirectory $env:TEMP -WindowStyle Hidden -PassThru
    if (!$process.WaitForExit(60000)) { $process.Kill(); throw "Launcher check timed out: $Name" }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "Launcher check failed: $Name (exit $($process.ExitCode))" }
    $file=Get-Item -LiteralPath $resultPath
    if ($file.LastWriteTime -lt $started) { throw "Stale check output: $Name" }
    $text=[IO.File]::ReadAllText($resultPath)
    if ($Cli -and !$text.Contains('NATIVE_CLI_RESULT=passed')) { throw "Missing CLI pass record: $Name" }
    Copy-Item -LiteralPath $resultPath -Destination (Join-Path $reportRoot ($Name+[IO.Path]::GetExtension($Result)))
    $checks.Add($Name)
    Write-Output "PASS: $Name"
}
foreach($task in @('component-outcome-checks','shared-storage-checks','physical-planning-checks','partition-picker-checks')) {
    Invoke-LauncherCheck -Arguments @('--cli',$task) -Result 'logs/native-cli-result.txt' -Name $task -Cli
}
Invoke-LauncherCheck -Arguments @('--shared-storage-ui-checks') -Result 'logs/shared-storage-ui-checks.json' -Name 'shared-storage-ui-checks'
Invoke-LauncherCheck -Arguments @('--installation-result-checks') -Result 'logs/installation-result-checks.json' -Name 'installation-result-checks'
Invoke-LauncherCheck -Arguments @('--options-checks') -Result 'logs/options-checks.json' -Name 'options-checks'
$powershell=Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
foreach($task in @('test-partition-deletion','test-format-remaining','test-disk-inventory')) {
    # These scripts replace Storage/native disk entry points with fixtures.
    $output=& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot ('scripts/'+$task+'.ps1')) 2>&1 | Out-String
    $output | Set-Content -LiteralPath (Join-Path $reportRoot ($task+'.txt')) -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Mocked storage check failed: $task" }
    $checks.Add($task)
    Write-Output "PASS: $task"
}
[pscustomobject]@{version=$release.version;passed=$true;checks=@($checks);physical_disk_writes=$false;working_directory=$env:TEMP} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'result.json') -Encoding utf8
Write-Output "RELEASE_SMOKE_RESULT=passed; report=$reportRoot"
