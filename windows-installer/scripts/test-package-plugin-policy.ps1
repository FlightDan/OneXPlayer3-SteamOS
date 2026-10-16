$ErrorActionPreference = 'Stop'
# Load the production policy and copy code without executing package preflight,
# reading real caches, building an archive, or contacting a device.
$scriptPath = Join-Path $PSScriptRoot 'make-development-package.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in 'Test-PackageFile','Assert-PackagePluginPolicy','Copy-PackageTree') {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if (!$definition) { throw "Production function missing: $name" }
    Invoke-Expression $definition.Extent.Text
}
$gate = $ast.Find({ param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$selfInstalledPlugins' }, $true)
$explicitCopy = $ast.Find({ param($node) $node -is [Management.Automation.Language.ForEachStatementAst] -and $node.Extent.Text.StartsWith('foreach ($item in @(@(''decky''') }, $true)
if (!$gate -or !$explicitCopy) { throw 'Production package policy entry point missing.' }
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('oxp3-package-policy-' + [guid]::NewGuid().ToString('N'))
$projectRoot = Join-Path $fixtureRoot 'source'
$source = Join-Path $projectRoot 'cache/plugins'
$PublicRelease = $false
$fixtures = @('plugins.json','third-party.json','unknown.json','decky/PluginLoader',
    'decky/plugin_loader-release.service','decky/source-v3.2.10.zip',
    'steamgriddb/steamgriddb-1.8.1.zip','protondb/protondb-1.3.4.zip',
    'tabmaster/tabmaster-2.15.1+oxp3.1.zip','autoflatpaks/autoflatpaks-1.6.8+oxp3.1.zip',
    'hltb/hltb-2.0.12.zip','animation-changer/animation-changer-1.3.2.zip',
    'css-loader/css-loader-2.1.2.zip','deck-settings/deck-settings-1.2.6.zip','future-plugin/plugin.zip')
try {
    foreach ($path in $fixtures) {
        $file = Join-Path $source $path
        New-Item -ItemType Directory -Force (Split-Path $file -Parent) | Out-Null
        Set-Content -LiteralPath $file -Value 'fixture'
    }
    foreach ($version in '0.1.0','0.1.3','0.1.4-beta','0.1.4','0.2.0') {
        $release = @{version=$version}
        Invoke-Expression $gate.Extent.Text
        $destination = Join-Path $fixtureRoot $version
        Copy-PackageTree $source 'cache/plugins'
        Invoke-Expression $explicitCopy.Extent.Text
        $actual = @(Get-ChildItem (Join-Path $destination 'cache/plugins') -Recurse -File | ForEach-Object {
            [IO.Path]::GetRelativePath((Join-Path $destination 'cache/plugins'), $_.FullName).Replace('\','/')
        } | Sort-Object)
        if ($version -in @('0.1.0','0.1.3')) {
            if ($selfInstalledPlugins -or 'plugins.json' -notin $actual -or 'tabmaster/tabmaster-2.15.1+oxp3.1.zip' -notin $actual) {
                throw "Historical plugin packaging changed: $version"
            }
        } else {
            $expected = @($fixtures | Where-Object { $_.StartsWith('decky/') } | Sort-Object)
            if (Compare-Object $expected $actual) { throw "Unexpected plugin package inventory: $version ($actual)" }
            Assert-PackagePluginPolicy $destination
            # Fail closed if a later copy step reintroduces either a manifest or archive.
            foreach ($rogue in 'plugins.json','steamgriddb/steamgriddb-1.8.1.zip') {
                $file = Join-Path $destination "cache/plugins/$rogue"
                New-Item -ItemType Directory -Force (Split-Path $file -Parent) | Out-Null
                Set-Content -LiteralPath $file -Value 'fixture'
                $rejected = $false
                try { Assert-PackagePluginPolicy $destination } catch { $rejected = $_.Exception.Message -like 'Retired third-party*' }
                if (!$rejected) { throw "Package assertion accepted $rogue" }
                Remove-Item -LiteralPath $file
            }
        }
    }
    foreach ($name in 'collect-desktop-runtime.py','deploy-windows-reboot-live.py','repair-project-relocation.ps1') {
        if (Test-PackageFile 'scripts' $name) { throw "Local-only helper accepted: $name" }
    }
    if (!(Test-PackageFile 'scripts' 'read-disks.ps1') -or
        !(Test-PackageFile 'cache/integration' 'sources/manager-source.tar.gz')) { throw 'Runtime helper or attribution was excluded.' }
    if (@(Get-ChildItem -LiteralPath $source -Recurse -File).Count -ne $fixtures.Count) { throw 'Source fixture was mutated.' }
    Write-Output 'PASS: production package filter, explicit copies, staged assertions, historical versions, and local-only helper exclusions'
} finally {
    $resolved = [IO.Path]::GetFullPath($fixtureRoot)
    if (!$resolved.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup path.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
