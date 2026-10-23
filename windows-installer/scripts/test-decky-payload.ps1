param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'make-development-package.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-PinnedDeckyPayload' }, $true)
if (!$definition) { throw 'Production Decky preflight missing.' }
Invoke-Expression $definition.Extent.Text
Assert-PinnedDeckyPayload $ProjectRoot
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('oxp3-decky-preflight-' + [guid]::NewGuid().ToString('N'))
$cache = Join-Path $fixture 'cache/plugins/decky'
$components = Join-Path $fixture 'components'
New-Item -ItemType Directory -Path $cache,$components -Force | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
function Write-Json($Path, $Value) { [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 8), $utf8) }
function Reset-Fixture {
    $files = @{ 'PluginLoader'='ELF fixture'; 'LICENSE'='GPL fixture'; 'VERSION'="3.3.0`n"; 'plugin_loader-release.service'='service fixture'; 'source-v3.3.0.zip'='source fixture' }
    $records = @{}
    foreach ($name in $files.Keys) {
        $path = Join-Path $cache $name
        [IO.File]::WriteAllText($path, $files[$name], $utf8)
        $records[$name] = @{bytes=(Get-Item -LiteralPath $path).Length; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    Write-Json (Join-Path $components 'decky-release.json') @{schema=1; version='3.3.0'; source_commit=('a'*40); binary=$records.PluginLoader; source=$records.'source-v3.3.0.zip'}
    Write-Json (Join-Path $components 'catalog.json') @{components=@(); plugins=@(@{id='decky'; version='3.3.0'})}
    Write-Json (Join-Path $cache 'manifest.json') @{schema=1; version='3.3.0'; source_commit=('a'*40); files=$records}
}
try {
    Reset-Fixture
    Assert-PinnedDeckyPayload $fixture
    $cases = @(
        { [IO.File]::WriteAllText((Join-Path $cache 'PluginLoader'), 'changed', $utf8) },
        { [IO.File]::WriteAllText((Join-Path $cache 'VERSION'), "3.2.10`n", $utf8) },
        { Remove-Item -LiteralPath (Join-Path $components 'decky-release.json') },
        { $data=Get-Content -LiteralPath (Join-Path $cache 'manifest.json') -Raw | ConvertFrom-Json; $data.source_commit='b'*40; Write-Json (Join-Path $cache 'manifest.json') $data },
        { $data=Get-Content -LiteralPath (Join-Path $components 'catalog.json') -Raw | ConvertFrom-Json; $data.plugins[0].version='3.2.10'; Write-Json (Join-Path $components 'catalog.json') $data },
        { $data=Get-Content -LiteralPath (Join-Path $cache 'manifest.json') -Raw | ConvertFrom-Json; $data.files.PSObject.Properties.Remove('LICENSE'); Write-Json (Join-Path $cache 'manifest.json') $data; Remove-Item -LiteralPath (Join-Path $cache 'LICENSE') },
        { [IO.File]::WriteAllText((Join-Path $cache 'source-v3.2.10.zip'), 'old', $utf8) }
    )
    foreach ($change in $cases) {
        Reset-Fixture
        & $change
        $refused = $false
        try { Assert-PinnedDeckyPayload $fixture } catch { $refused = $true }
        if (!$refused) { throw 'Production Decky preflight accepted a stale/incomplete fixture.' }
    }
    Write-Output "PASS: production Decky cache and $($cases.Count) stale/incomplete package fixtures"
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    if (!$resolved.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup path.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
