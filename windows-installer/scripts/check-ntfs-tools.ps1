param([string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
$source = Join-Path $ProjectRoot 'components/partition-mount'
$tools = Join-Path $source 'tools'
$pin = Get-Content -LiteralPath (Join-Path $source 'ntfs-tools-source.json') -Raw | ConvertFrom-Json
$manifest = Get-Content -LiteralPath (Join-Path $tools 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.architecture -ne 'x86_64' -or $manifest.static -ne $true -or
    $manifest.version -ne $pin.version -or $manifest.source.url -ne $pin.source.url -or
    $manifest.source.sha256 -ne $pin.source.sha256) { throw 'Stale NTFS tools provenance.' }
$expected = @('ntfs_status','ntfsfix','COPYING','source.tar.gz')
if ((Compare-Object ($expected | Sort-Object) (@($manifest.files.PSObject.Properties.Name) | Sort-Object)) -or
    (Compare-Object (($expected + 'manifest.json') | Sort-Object) (@(Get-ChildItem -LiteralPath $tools -Force | ForEach-Object Name) | Sort-Object))) {
    throw 'Unexpected NTFS tools files.'
}
foreach ($name in $expected) {
    $path = Join-Path $tools $name
    $record = $manifest.files.$name
    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -ne $record.size -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.sha256) { throw "Stale NTFS tool: $name" }
}
if ((Get-FileHash -LiteralPath (Join-Path $tools 'source.tar.gz') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin.source.sha256) {
    throw 'NTFS corresponding source mismatch.'
}
foreach ($name in 'ntfs_status.c','ntfs-tools-build.sh') {
    if ((Get-FileHash -LiteralPath (Join-Path $source $name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.build_inputs.$name) {
        throw "Rebuild NTFS tools from current source: $name"
    }
}
if ((Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'guest/ntfs-tools-build.sh') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.build_inputs.'ntfs-tools-build.sh') {
    throw 'NTFS build source changed; rebuild and prepare integration.'
}
$integration = Get-Content -LiteralPath (Join-Path $ProjectRoot 'cache/integration/manifest.json') -Raw | ConvertFrom-Json
$inventoryPath = Join-Path $ProjectRoot 'cache/integration/partition-mount/source-manifest.json'
if ((Get-FileHash -LiteralPath $inventoryPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $integration.'partition-mount'.source_manifest_sha256) {
    throw 'Stale partition mount source manifest.'
}
$inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json
foreach ($entry in $inventory.files.PSObject.Properties) {
    if ($entry.Name -match '(^|/)\.\.?(/|$)|[\\:]' -or $entry.Name.StartsWith('/')) { throw 'Unsafe partition mount source manifest path.' }
    $path = Join-Path $source $entry.Name
    if ((Get-Item -LiteralPath $path).Length -ne $entry.Value.size -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value.sha256) { throw "Stale partition mount source: $($entry.Name)" }
}
Write-Output "NTFS tools and partition mount sources verified: $($manifest.version)"
