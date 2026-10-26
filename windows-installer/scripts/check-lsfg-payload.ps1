param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$ArchiveRoot = $ProjectRoot
)
$ErrorActionPreference = 'Stop'
$pin = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/lsfg-vk-release.json') -Raw | ConvertFrom-Json
$archive = Get-Item -LiteralPath (Join-Path $ArchiveRoot "cache/lsfg-vk/$($pin.archive.filename)")
if ($pin.schema -ne 1 -or $pin.id -ne 'lsfg-vk' -or $pin.version -ne '0.14.4' -or
    $pin.deployment -ne 'plugin-only-with-bundled-runtime' -or $archive.Length -ne $pin.archive.bytes -or
    (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin.archive.sha256) {
    throw 'LSFG-VK source archive differs from the pinned official release.'
}
$options = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/options.json') -Raw | ConvertFrom-Json
$option = @($options.plugins | Where-Object id -eq 'lsfg-vk')
$catalog = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/catalog.json') -Raw | ConvertFrom-Json
$item = @(@($catalog.components) + @($catalog.plugins) | Where-Object id -eq 'lsfg-vk')
if ($option.Count -ne 1 -or $option[0].default -ne $false -or
    (@($option[0].dependencies) -join ',') -ne 'decky' -or
    $item.Count -ne 1 -or $item[0].version -ne $pin.version) { throw 'LSFG-VK catalog/options metadata is stale.' }
$manifest = Get-Content -LiteralPath (Join-Path $ProjectRoot 'cache/integration/manifest.json') -Raw | ConvertFrom-Json
$component = $manifest.'lsfg-vk'
if ($component.version -ne $pin.version -or $component.archive_sha256 -ne $pin.archive.sha256 -or
    @($component.units).Count -ne 0 -or @($component.missing).Count -ne 0) { throw 'LSFG-VK integration metadata is stale.' }
$expected = @{}
$zip = [IO.Compression.ZipFile]::OpenRead($archive.FullName)
try {
    foreach ($entry in $zip.Entries) {
        if ($entry.FullName.EndsWith('/')) { continue }
        $prefix = 'Decky LSFG-VK/'
        if (!$entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { throw 'Unexpected LSFG-VK archive root.' }
        $relative = $entry.FullName.Substring($prefix.Length)
        $stream = $entry.Open()
        try { $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() }
        finally { $stream.Dispose() }
        $expected[$relative] = @{ sha256=$hash; bytes=$entry.Length }
    }
} finally { $zip.Dispose() }
if (@($component.files).Count -ne $expected.Count) { throw 'Incomplete LSFG-VK plugin payload.' }
$seen = @{}
foreach ($file in $component.files) {
    $prefix = 'var/lib/oxp3-installer/decky/runtime/plugins/Decky LSFG-VK/'
    if (!$file.target.StartsWith($prefix, [StringComparison]::Ordinal) -or $file.user -ne $false -or $file.mode -ne 420 -or
        !$file.source.StartsWith('lsfg-vk/', [StringComparison]::Ordinal) -or $file.source -match '(^|/)\.\.(/|$)|\\') {
        throw 'Unexpected LSFG-VK install target, source or ownership.'
    }
    $relative = $file.target.Substring($prefix.Length)
    if (!$expected.ContainsKey($relative) -or $seen.ContainsKey($relative)) { throw 'Unexpected or duplicate LSFG-VK member.' }
    $seen[$relative] = $true
    $staged = Get-Item -LiteralPath (Join-Path $ProjectRoot "cache/integration/$($file.source)")
    if ($staged.Length -ne $expected[$relative].bytes -or
        (Get-FileHash -LiteralPath $staged.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[$relative].sha256) {
        throw "Stale LSFG-VK payload: $relative"
    }
}
Write-Output "LSFG-VK $($pin.version) verified: $($seen.Count) unchanged plugin files; runtime $($pin.runtime.version) bundled."
