param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$pins = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/opti2xmx-release.json') -Raw | ConvertFrom-Json
$manifest = Get-Content -LiteralPath (Join-Path $ProjectRoot 'cache/integration/manifest.json') -Raw | ConvertFrom-Json
function Assert-PinnedFile([string]$Path, [string]$Digest) {
    if ($Digest -notmatch '^[a-f0-9]{64}$') { throw 'Invalid Opti file digest' }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) { throw 'Opti asset must be a regular file' }
    $ancestor = $item
    while ($null -ne $ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked Opti asset refused' }
        $ancestor = if ($ancestor -is [IO.DirectoryInfo]) { $ancestor.Parent } else { $ancestor.Directory }
    }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Digest) {
        throw "Stale Opti asset: $Path"
    }
}
if ($pins.schema -ne 1 -or $pins.runtime.published -ne $true -or $manifest.opti2xmx.runtime_archive -ne 'opti2xmx/runtime.tar.gz') {
    throw 'Invalid pinned Opti deployment metadata'
}
$expected = @($pins.files.PSObject.Properties)
if ($expected.Count -ne 16 -or @($manifest.opti2xmx.files).Count -ne $expected.Count + 1) {
    throw 'Unexpected Opti integration membership'
}
foreach ($file in $expected) {
    $relative = $file.Name
    if ($relative.Contains('\') -or $relative.Contains(':') -or ($relative.Split('/') | Where-Object { $_ -in @('','.', '..') })) { throw 'Unsafe pinned Opti member' }
    Assert-PinnedFile (Join-Path $ProjectRoot "components/opti2xmx/$relative") $file.Value
    $target = 'home/deck/homebrew/plugins/opti2xmx/' + $relative
    $entry = @($manifest.opti2xmx.files | Where-Object target -eq $target)
    if ($entry.Count -ne 1 -or $entry[0].mode -ne 420 -or $entry[0].user -ne $false) { throw 'Invalid Opti integration target' }
    $source = $entry[0].source
    if ($source -notmatch '^opti2xmx/[0-9]{3}\.bin$') { throw 'Unsafe Opti integration source' }
    Assert-PinnedFile (Join-Path $ProjectRoot "cache/integration/$source") $file.Value
}
$config = @($manifest.opti2xmx.files | Where-Object target -eq 'home/deck/.local/share/opti2xmx/runtime.json')
if ($config.Count -ne 1) { throw 'Missing fixed Opti runtime configuration' }
$runtime = Join-Path $ProjectRoot 'cache/integration/opti2xmx/runtime.tar.gz'
if ((Get-Item -LiteralPath $runtime).Length -ne $pins.runtime.size_bytes) { throw 'Stale Opti runtime size' }
Assert-PinnedFile $runtime $pins.runtime.sha256
Write-Output "OPTI_PAYLOAD=passed; plugin=$($pins.plugin_version); members=$($expected.Count); runtime=$($pins.runtime.size_bytes)"
