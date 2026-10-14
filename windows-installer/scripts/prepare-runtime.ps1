param([string]$SevenZip = 'C:\Program Files\7-Zip\7z.exe')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) { throw 'Development preparation requires 7-Zip. The released tool will contain the prepared runtime.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Development preparation requires Node.js.' }
$cache = Join-Path $projectRoot 'cache'
New-Item -ItemType Directory -Force $cache | Out-Null
$resources = @(
    @{ Name = 'qemu-w64-setup-20260811.exe'; Url = 'https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe' },
    @{ Name = 'alpine-virt-3.23.6-x86_64.iso'; Url = 'https://dl-cdn.alpinelinux.org/alpine/v3.23/releases/x86_64/alpine-virt-3.23.6-x86_64.iso' }
)
foreach ($resource in $resources) {
    $destination = Join-Path $cache $resource.Name
    if (-not (Test-Path -LiteralPath $destination)) {
        $partial = "$destination.part"
        & curl.exe -fL --retry 2 --connect-timeout 20 --max-time 600 -o $partial $resource.Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $($resource.Name); partial file retained, not usable as a runtime." }
        Move-Item -LiteralPath $partial -Destination $destination
    }
}
# Extract the installer as an archive: never run its setup executable.
& $SevenZip x (Join-Path $cache $resources[0].Name) "-o$(Join-Path $projectRoot 'runtime/qemu-full')" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'QEMU extraction failed.' }
& $SevenZip x (Join-Path $cache $resources[1].Name) "-o$(Join-Path $projectRoot 'runtime/alpine')" boot/vmlinuz-virt boot/initramfs-virt -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Alpine boot extraction failed.' }
& node (Join-Path $PSScriptRoot 'bundle-qemu.mjs')
if ($LASTEXITCODE -ne 0) { throw 'QEMU dependency bundle failed.' }
