[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ZigArchive,
    [Parameter(Mandatory = $true)][string]$WimlibArchive,
    [Parameter(Mandatory = $true)][string]$WimlibSource,
    [Parameter(Mandatory = $true)][string]$WorkDirectory,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$ZigExe
)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $sourceRoot 'dependency-source.json') -Raw | ConvertFrom-Json
function Assert-PinnedFile([string]$Path, [string]$Expected, [long]$Size = 0) {
    $item = Get-Item -LiteralPath $Path
    if ($Size -and $item.Length -ne $Size) { throw "Unexpected size: $Path" }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {
        throw "SHA-256 mismatch: $Path"
    }
}
Assert-PinnedFile $ZigArchive $pins.compiler.sha256 $pins.compiler.size
Assert-PinnedFile $WimlibArchive $pins.wimlib.binary_sha256 $pins.wimlib.binary_size
Assert-PinnedFile $WimlibSource $pins.wimlib.source_sha256
$work = [IO.Path]::GetFullPath($WorkDirectory)
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) {
    if (Get-ChildItem -LiteralPath $output -Force | Select-Object -First 1) {
        throw 'OutputDirectory must be empty; prior build files must not enter a new payload.'
    }
}
New-Item -ItemType Directory -Force -Path $work, $output | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (!$ZigExe) {
    $compilerRoot = Join-Path $work 'compiler'
    if (Test-Path -LiteralPath $compilerRoot) { throw 'Use a fresh WorkDirectory for compiler extraction.' }
    [IO.Compression.ZipFile]::ExtractToDirectory([IO.Path]::GetFullPath($ZigArchive), $compilerRoot)
    $ZigExe = Join-Path $compilerRoot 'zig-x86_64-windows-0.15.2/zig.exe'
} else {
    # Reuse an already extracted compiler only if its executable matches the
    # executable inside the pinned official compiler archive.
    $compilerZip = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($ZigArchive))
    try {
        $entry = $compilerZip.GetEntry('zig-x86_64-windows-0.15.2/zig.exe')
        if (!$entry) { throw 'Compiler executable absent from pinned archive.' }
        $stream = $entry.Open()
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $expectedExeHash = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose(); $sha.Dispose() }
        Assert-PinnedFile $ZigExe $expectedExeHash $entry.Length
    } finally { $compilerZip.Dispose() }
}
if ((& $ZigExe version).Trim() -ne $pins.compiler.version) { throw 'Unexpected Zig compiler version.' }
$include = Join-Path $work 'include'
$binaries = Join-Path $output 'bin'
$licenses = Join-Path $output 'licenses/wimlib'
$sources = Join-Path $output 'sources'
New-Item -ItemType Directory -Force -Path $include, $binaries, $licenses, $sources | Out-Null
$dependencyZip = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($WimlibArchive))
try {
    $members = @{
        'libwim-15.dll' = (Join-Path $binaries 'libwim-15.dll')
        'devel/wimlib.h' = (Join-Path $include 'wimlib.h')
    }
    foreach ($name in $pins.wimlib.license_members) { $members[$name] = Join-Path $licenses $name }
    foreach ($name in $members.Keys) {
        $entry = $dependencyZip.GetEntry($name)
        if (!$entry) { throw "Pinned dependency member missing: $name" }
        # Only the compiler input header may already exist in a reused build
        # work directory. Output payload files always require a fresh directory.
        $overwriteHeader = $name -eq 'devel/wimlib.h'
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $members[$name], $overwriteHeader)
    }
} finally { $dependencyZip.Dispose() }
Assert-PinnedFile (Join-Path $binaries 'libwim-15.dll') $pins.wimlib.library_sha256 $pins.wimlib.library_size
# Cache writes stay inside the caller-selected work directory.
$oldGlobal = $env:ZIG_GLOBAL_CACHE_DIR
$oldLocal = $env:ZIG_LOCAL_CACHE_DIR
try {
    $env:ZIG_GLOBAL_CACHE_DIR = Join-Path $work 'zig-global-cache'
    $env:ZIG_LOCAL_CACHE_DIR = Join-Path $work 'zig-local-cache'
    & $ZigExe cc -target x86_64-windows-gnu -std=c11 -O2 -shared -s -Wall -Wextra -Werror `
        -I $include (Join-Path $sourceRoot 'fsrxdec.c') (Join-Path $sourceRoot 'fsrxdec.def') `
        -o (Join-Path $binaries 'fsrxdec.dll')
    if ($LASTEXITCODE -ne 0) { throw 'fsrxdec compiler failed.' }
    # Zig also writes a developer import library. It is not a runtime dependency.
    $importLibrary = Join-Path $binaries 'fsrxdec.lib'
    if (Test-Path -LiteralPath $importLibrary) { Remove-Item -LiteralPath $importLibrary }
    $binaryNames = @(Get-ChildItem -LiteralPath $binaries -File | Sort-Object Name | Select-Object -ExpandProperty Name)
    if (($binaryNames -join ',') -ne 'fsrxdec.dll,libwim-15.dll') { throw 'Unexpected runtime binary set.' }
} finally {
    $env:ZIG_GLOBAL_CACHE_DIR = $oldGlobal
    $env:ZIG_LOCAL_CACHE_DIR = $oldLocal
}
Copy-Item -LiteralPath $WimlibSource -Destination (Join-Path $sources 'wimlib-1.14.5.tar.gz')
Copy-Item -LiteralPath (Join-Path $sourceRoot 'LICENSE') -Destination (Join-Path $output 'licenses/fsrxdec-LICENSE.txt')
$adapterSources = Join-Path $sources 'fsr_compat'
New-Item -ItemType Directory -Path $adapterSources | Out-Null
foreach ($name in @('fsrxdec.c', 'fsrxdec.def', 'dependency-source.json', 'build.ps1', 'README.md', 'test_fsrxdec.py', 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination $adapterSources
}
$files = @(Get-ChildItem -LiteralPath $output -File -Recurse | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = [IO.Path]::GetRelativePath($output, $_.FullName).Replace('\', '/')
        size = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
$manifest = [ordered]@{
    schema = 1; adapter = 'fsrxdec'; version = '1'; architecture = 'x86_64'; compiler = $pins.compiler
    files = @($files | Where-Object { $_.path.StartsWith('bin/') })
    distribution_files = @($files | Where-Object { !$_.path.StartsWith('bin/') })
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'manifest.json') -Encoding utf8
Write-Output (Join-Path $output 'manifest.json')
