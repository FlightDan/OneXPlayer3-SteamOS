param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$pins = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/opti2xmx-release.json') -Raw | ConvertFrom-Json
$optiPins = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/optiscaler-release.json') -Raw | ConvertFrom-Json
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
$baseMembers = @('plugin.json','package.json','main.py','manager.py','opti.py',
    'download_progress.py','runtime_setup.py','runtime-source.json','per_game.py',
    'dist/index.js','README.md','README.zh-CN.md','LICENSE','THIRD_PARTY_NOTICES.md',
    'docs/RUNTIME.md','docs/FRAME_GENERATION.md')
$fsrMembers = @('fsr.py','fsr_cm.py','fsr-source.json','docs/FSR_XMX.md','fsr_compat/manifest.json')
$compatMembers = @('bin/fsrxdec.dll','bin/libwim-15.dll',
    'licenses/fsrxdec-LICENSE.txt','licenses/wimlib/COPYING.GPLv3.txt',
    'licenses/wimlib/COPYING.LGPL.txt','licenses/wimlib/COPYING.libdivsufsort-lite.txt',
    'licenses/wimlib/COPYING.txt','sources/fsr_compat/build.ps1',
    'sources/fsr_compat/dependency-source.json','sources/fsr_compat/fsrxdec.c',
    'sources/fsr_compat/fsrxdec.def','sources/fsr_compat/LICENSE',
    'sources/fsr_compat/README.md','sources/fsr_compat/test_fsrxdec.py',
    'sources/wimlib-1.14.5.tar.gz') | ForEach-Object { 'fsr_compat/' + $_ }
$requiredMembers = if ($expected.Name -contains 'fsr.py') { $baseMembers + $fsrMembers + $compatMembers } else { $baseMembers }
if ((Compare-Object ($requiredMembers | Sort-Object) ($expected.Name | Sort-Object) -CaseSensitive) -or
    $optiPins.schema -ne 1 -or @($optiPins.archives).Count -lt 1 -or
    @($manifest.opti2xmx.files).Count -ne $expected.Count + 1 + @($optiPins.archives).Count) {
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
foreach ($archive in $optiPins.archives) {
    $target = 'home/deck/.local/share/opti2xmx/downloads/' + $archive.tag + '/' + $archive.filename
    $entry = @($manifest.opti2xmx.files | Where-Object target -eq $target)
    if ($entry.Count -ne 1 -or $entry[0].mode -ne 420 -or $entry[0].user -ne $true -or
        $entry[0].source -notmatch '^opti2xmx/[0-9]{3}\.bin$') { throw 'Missing or invalid offline OptiScaler cache' }
    $file = Join-Path $ProjectRoot ('cache/integration/' + $entry[0].source)
    if ((Get-Item -LiteralPath $file).Length -ne $archive.size_bytes) { throw 'Stale OptiScaler archive size' }
    Assert-PinnedFile $file $archive.sha256
}
$runtime = Join-Path $ProjectRoot 'cache/integration/opti2xmx/runtime.tar.gz'
if ((Get-Item -LiteralPath $runtime).Length -ne $pins.runtime.size_bytes) { throw 'Stale Opti runtime size' }
Assert-PinnedFile $runtime $pins.runtime.sha256
Write-Output "OPTI_PAYLOAD=passed; plugin=$($pins.plugin_version); members=$($expected.Count); runtime=$($pins.runtime.size_bytes); offline_optiscaler=$($optiPins.archives.version -join ',')"
