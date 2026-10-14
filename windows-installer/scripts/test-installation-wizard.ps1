param(
    [ValidateSet('checks','cancel','internal','external')][string]$Mode = 'checks',
    [Parameter(Mandatory=$true)][string]$SourcePath
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $projectRoot 'runtime/dotnet/dotnet.exe'
$app = Join-Path $projectRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll'
$source = [IO.Path]::GetFullPath($SourcePath)
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Missing input image' }
$arguments = switch ($Mode) {
    'checks' { @('--wizard-checks', $source) }
    'cancel' { @('--wizard-cancel-prepared', $source, 'external') }
    'internal' { @('--wizard-run-image', $source, 'internal') }
    'external' { @('--wizard-run-prepared', $source, 'external') }
}
& $runtime $app @arguments
if ($LASTEXITCODE -ne 0) { throw "Wizard $Mode check failed; inspect logs and work/install-session-*/session.json" }
if ($Mode -eq 'checks') {
    $proof = (Get-Content (Join-Path $projectRoot 'logs/wizard-checks-result.txt') -Raw).Trim()
    $result = Get-Content -LiteralPath (Join-Path $proof 'checks.json') -Raw | ConvertFrom-Json
    if (-not $result.passed) { throw 'UI navigation/layout checks did not pass' }
    & $runtime $app --cli installation-controller-checks $source
    if ($LASTEXITCODE -ne 0) { throw 'Controller guard checks failed' }
    $guards = Get-Content (Join-Path $projectRoot 'logs/installation-controller-checks.json') -Raw | ConvertFrom-Json
    if (-not $guards.passed) { throw 'Controller guards did not pass' }
    Write-Output "UI proof: $proof"
    Write-Output "Controller checks: $($guards.events.Count)"
} else {
    $session = Get-ChildItem (Join-Path $projectRoot 'work') -Directory -Filter 'install-session-*' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    Get-Content -LiteralPath (Join-Path $session.FullName 'session.json')
}
