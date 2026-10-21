param(
    [ValidateSet('init-key','status','preflight','prepare')][string]$Action = 'status',
    [string]$Version = '0.1.4',
    [string]$OptiPlugin,
    [string]$OptiRuntime,
    [string]$OpenSsl,
    [string]$OutputDirectory,
    [string]$PreviousCatalog,
    [string]$PreviousSignature,
    [string]$KeyStore,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython -PathType Leaf) { $Python = $bundledPython }
    else { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
}
$publisherArguments = @('-B', (Join-Path $PSScriptRoot 'publisher.py'), $Action, '--version', $Version)
if ($OptiPlugin) { $publisherArguments += @('--opti-plugin', $OptiPlugin) }
if ($OptiRuntime) { $publisherArguments += @('--opti-runtime', $OptiRuntime) }
if ($OpenSsl) { $publisherArguments += @('--openssl', $OpenSsl) }
if ($OutputDirectory) { $publisherArguments += @('--output', $OutputDirectory) }
if ($PreviousCatalog) { $publisherArguments += @('--previous-catalog', $PreviousCatalog) }
if ($PreviousSignature) { $publisherArguments += @('--previous-signature', $PreviousSignature) }
if ($KeyStore) { $publisherArguments += @('--store', $KeyStore) }
& $Python @publisherArguments
exit $LASTEXITCODE
