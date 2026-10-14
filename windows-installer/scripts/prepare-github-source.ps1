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
New-Item -ItemType Directory -Path (Join-Path $destination 'windows-installer') | Out-Null
foreach ($relative in $projectFiles) { Copy-Item -LiteralPath (Join-Path $projectRoot $relative) -Destination (Join-Path $destination 'windows-installer') }
foreach ($tree in @('app','components','guest','scripts','docs','licenses')) {
    foreach ($item in Get-ChildItem -LiteralPath (Join-Path $projectRoot $tree) -Recurse -File) {
        $relative = [IO.Path]::GetRelativePath($projectRoot, $item.FullName)
        if ($relative -match '(^|[\\/])(bin|obj|node_modules|__pycache__|\.impeccable)([\\/]|$)') { continue }
        if ($item.Extension -in @('.pyc','.pyo','.user','.suo','.pdb')) { continue }
        if ($relative -eq 'scripts\collect-desktop-runtime.py' -or $relative -eq 'scripts/collect-desktop-runtime.py') { continue }
        if ($relative -match '^docs[\\/](early-repair-audit-20261014|final-installer-validation|five-repairs-20261014|g3e-repair-status|permission-regression-20261014)\.json$') { continue }
        $target = Join-Path $destination "windows-installer/$relative"
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $target
    }
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
