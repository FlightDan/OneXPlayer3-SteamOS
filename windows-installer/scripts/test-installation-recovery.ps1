param(
    [ValidateSet('compact','internal','external')][string]$Mode = 'compact',
    [string]$SourcePath
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $projectRoot 'runtime/dotnet/dotnet.exe'
$app = Join-Path $projectRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll'
$result = Join-Path $projectRoot 'logs/native-cli-result.txt'
if ($Mode -eq 'compact') {
    & $runtime $app --cli native-partition-recovery-checks
    if ($LASTEXITCODE -ne 0) { throw 'Recovery guard checks failed; inspect logs/native-cli-result.txt' }
    Get-Content -LiteralPath $result
    return
}
$source = [IO.Path]::GetFullPath($SourcePath)
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'A prepared image is required' }
$kind = if ($Mode -eq 'internal') { 'InternalShared' } else { 'ExternalDisk' }
& $runtime $app --cli native-partition-recovery-fixture $source $kind
if ($LASTEXITCODE -ne 0) { throw 'Owned crash fixture failed' }
$line = Get-Content -LiteralPath $result | Where-Object { $_.StartsWith('RECOVERY_SESSION=') } | Select-Object -Last 1
if (-not $line) { throw 'Missing interrupted session proof' }
$sessionPath = $line.Substring('RECOVERY_SESSION='.Length)
& $runtime $app --wizard-resume $sessionPath
if ($LASTEXITCODE -ne 0) { throw "Native wizard recovery failed: $sessionPath" }
$session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
if ($session.Status -ne 'complete') { throw 'Recovered task did not complete' }
$boot = Get-Content -LiteralPath (Join-Path $session.Deployment 'boot-proof.json') -Raw | ConvertFrom-Json
if (-not $boot.passed) { throw 'Missing independent UEFI boot proof' }
Write-Output "Recovered session: $sessionPath"
Write-Output "Boot proof: $($session.Deployment)\boot-proof.json"
