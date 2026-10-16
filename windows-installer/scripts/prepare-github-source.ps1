param([string]$Stamp = (Get-Date -Format 'yyyyMMdd-HHmmss'))
$ErrorActionPreference = 'Stop'
if ($Stamp -notmatch '^\d{8}-\d{6}$') { throw 'Invalid source export stamp' }
$projectRoot = Split-Path $PSScriptRoot -Parent
$workspaceRoot = Split-Path $projectRoot -Parent
$destination = Join-Path $projectRoot "dist/github-source-$Stamp"
if (Test-Path -LiteralPath $destination) { throw 'Use a fresh source export stamp' }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$rootFiles = @('README.md','README.en.md','LICENSE','THIRD_PARTY_NOTICES.md','ROADMAP.md','GIT_WORKSPACE.md','.gitignore','.gitattributes')
$projectFiles = @('README.md','IMPLEMENTATION_STATUS.md','.gitignore','Launch.cmd')
foreach ($relative in $rootFiles) { Copy-Item -LiteralPath (Join-Path $workspaceRoot $relative) -Destination $destination }
# Preserve the public 0.1.3 screenshot/license URLs alongside canonical paths.
$legacyScreenshots = @('decky-plugins.png','hdr-game-mode.png','native-tdp-15w.png',
    'native-tdp-20w.png','native-tdp-40w.png','native-xess-settings.png','opti2xmx-xmx.png',
    'oxp3-fan.png','waydroid-desktop.png','waydroid-steam-entry.png','xess-gameplay.png')
New-Item -ItemType Directory -Path (Join-Path $destination 'docs/screenshots') -Force | Out-Null
foreach ($name in $legacyScreenshots) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "docs/screenshots/$name") -Destination (Join-Path $destination "docs/screenshots/$name")
}
New-Item -ItemType Directory -Path (Join-Path $destination 'licenses') -Force | Out-Null
foreach ($name in @('Opti2XMX-AGPL-BSD.txt','upstream-fixes-MIT.txt')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "licenses/$name") -Destination (Join-Path $destination "licenses/$name")
}
New-Item -ItemType Directory -Path (Join-Path $destination 'windows-installer') | Out-Null
foreach ($relative in $projectFiles) { Copy-Item -LiteralPath (Join-Path $projectRoot $relative) -Destination (Join-Path $destination 'windows-installer') }
foreach ($tree in @('app','components','guest','scripts','docs','licenses')) {
    foreach ($item in Get-ChildItem -LiteralPath (Join-Path $projectRoot $tree) -Recurse -File) {
        $relative = [IO.Path]::GetRelativePath($projectRoot, $item.FullName)
        if ($relative -match '(^|[\\/])(bin|obj|node_modules|__pycache__|\.impeccable)([\\/]|$)') { continue }
        if ($item.Extension -in @('.pyc','.pyo','.user','.suo','.pdb')) { continue }
        if ($tree -eq 'scripts' -and $item.Name -in @('collect-desktop-runtime.py','deploy-windows-reboot-live.py','repair-project-relocation.ps1')) { continue }
        if ($relative -match '^docs[\\/](early-repair-audit-20261014|final-installer-validation|five-repairs-20261014|g3e-repair-status|permission-regression-20261014)\.json$') { continue }
        $target = Join-Path $destination "windows-installer/$relative"
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $target
    }
}
# The installer embeds the maintained GTK runtime from this explicit source set.
$maintenanceRoot = Join-Path $workspaceRoot 'steamos-maintenance'
$maintenanceFiles = @('.gitignore','AGENTS.md','README.md','VALIDATION.md','DESIGN.md',
    'OXP3-Maintenance.desktop','Install-OXP3-Maintenance.desktop','oxp3-maintenance.sh','release-maintenance.ps1')
$maintenanceFiles += @(Get-ChildItem -LiteralPath $maintenanceRoot -File -Filter '*.py' | ForEach-Object { $_.Name })
$maintenanceFiles += @(Get-ChildItem -LiteralPath (Join-Path $maintenanceRoot 'oxp3_maintenance') -File -Filter '*.py' | ForEach-Object { 'oxp3_maintenance/' + $_.Name })
foreach ($tree in @('tests','release','docs')) {
    $maintenanceFiles += @(Get-ChildItem -LiteralPath (Join-Path $maintenanceRoot $tree) -Recurse -File | Where-Object {
        $_.Extension -in @('.py','.json','.md') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]'
    } | ForEach-Object { [IO.Path]::GetRelativePath($maintenanceRoot, $_.FullName) })
}
if (Test-Path -LiteralPath (Join-Path $maintenanceRoot 'trusted-public-key.pem')) { $maintenanceFiles += 'trusted-public-key.pem' }
foreach ($relative in $maintenanceFiles) {
    $target = Join-Path $destination "steamos-maintenance/$relative"
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $maintenanceRoot $relative) -Destination $target
}
$inventory = @(Get-ChildItem -LiteralPath $destination -Recurse -File | ForEach-Object {
    [pscustomobject]@{ path = [IO.Path]::GetRelativePath($destination, $_.FullName).Replace('\','/'); bytes = $_.Length }
} | Sort-Object path)
$report = Join-Path $projectRoot "logs/github-source-$Stamp.json"
New-Item -ItemType Directory -Path (Split-Path $report -Parent) -Force | Out-Null
[pscustomobject]@{ scope = 'Source snapshot only; no tests, commit, remote or upload'; directory = $destination;
    files = $inventory.Count; bytes = ($inventory | Measure-Object bytes -Sum).Sum; inventory = $inventory } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
Write-Output "Source candidate: $destination"
Write-Output "Files: $($inventory.Count); bytes: $(($inventory | Measure-Object bytes -Sum).Sum)"
Write-Output "Inventory: $report"
