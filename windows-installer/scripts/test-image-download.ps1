param([switch]$Official)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $projectRoot 'runtime/dotnet/dotnet.exe'
$app = Join-Path $projectRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll'
& $runtime $app --cli aria2-checks
if ($LASTEXITCODE -ne 0) { throw 'aria2 local/UI checks failed; inspect logs/native-cli-result.txt' }
$result = Get-Content (Join-Path $projectRoot 'logs/aria2-download-checks.json') -Raw | ConvertFrom-Json
if (-not $result.passed) { throw 'Missing passing aria2 report' }
Write-Output "aria2 checks passed: $($result.events.Count)"
if ($Official) {
    & $runtime $app --cli aria2-official-checks
    if ($LASTEXITCODE -ne 0) { throw 'aria2 official HTTPS sample checks failed; inspect logs/native-cli-result.txt' }
    Get-Content (Join-Path $projectRoot 'logs/aria2-official-checks.json')
}
