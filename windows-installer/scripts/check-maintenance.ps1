param([switch]$RequireKey)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$source = Join-Path (Split-Path $projectRoot -Parent) 'steamos-maintenance'
$staged = Join-Path $projectRoot 'cache/maintenance'
$manifest = Get-Content -LiteralPath (Join-Path $staged 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1) { throw 'Prepare the GTK runtime with scripts/prepare-maintenance.py first.' }
$expected = @('entry.py','OXP3-Maintenance.desktop')
$expected += @(Get-ChildItem -LiteralPath (Join-Path $source 'oxp3_maintenance') -Filter '*.py' -File | ForEach-Object { 'oxp3_maintenance/' + $_.Name })
$key = Join-Path $source 'trusted-public-key.pem'
if (Test-Path -LiteralPath $key) { $expected += 'trusted-public-key.pem' }
if ($RequireKey -and 'trusted-public-key.pem' -notin $expected) {
    throw 'Public releases require the real publisher key in steamos-maintenance/trusted-public-key.pem. QA keys must not be used.'
}
if ((Compare-Object ($expected | Sort-Object) (@($manifest.files.PSObject.Properties.Name) | Sort-Object))) { throw 'Maintenance runtime file list is stale.' }
$actual = @(Get-ChildItem -LiteralPath (Join-Path $staged 'app') -Recurse -File | ForEach-Object { [IO.Path]::GetRelativePath((Join-Path $staged 'app'), $_.FullName).Replace('\','/') })
if ((Compare-Object ($expected | Sort-Object) ($actual | Sort-Object))) { throw 'Unexpected files in maintenance staging.' }
foreach ($relative in $expected) {
    foreach ($base in @($source, (Join-Path $staged 'app'))) {
        $file = Join-Path $base $relative
        $item = Get-Item -LiteralPath $file -Force
        while ($null -ne $item) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked maintenance source refused: $file" }
            $item = if ($item -is [IO.DirectoryInfo]) { $item.Parent } else { $item.Directory }
        }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.files.$relative) { throw "Stale maintenance source: $relative. Restage before packaging." }
    }
}
if ('trusted-public-key.pem' -in $expected) {
    $pem = [IO.File]::ReadAllText($key)
    if ($pem -notmatch '\A\s*-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----\s*\z') { throw 'Invalid publisher public key.' }
    $der = [Convert]::FromBase64String(($Matches[1] -replace '\s',''))
    if ($der.Length -ne 44 -or [Convert]::ToHexString($der[0..11]) -ne '302A300506032B6570032100') { throw 'An Ed25519 publisher public key is required.' }
}
Write-Output "Maintenance runtime verified: $($expected.Count) files; publisher key: $('trusted-public-key.pem' -in $expected)"
