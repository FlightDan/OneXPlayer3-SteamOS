param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$payloadRoot = Join-Path $ProjectRoot 'runtime/payload'
$packages = @(Get-Content -LiteralPath (Join-Path $payloadRoot 'packages.json') -Raw | ConvertFrom-Json)
foreach ($required in @('e2fsprogs', 'e2fsprogs-extra')) {
    if (@($packages | Where-Object name -eq $required).Count -ne 1) {
        throw "Offline payload must contain $required (resize2fs is required for capacity expansion). Run prepare-offline.mjs before packaging."
    }
}
$seen = @{}
foreach ($package in $packages) {
    $filename = "$($package.name)-$($package.version).apk"
    if ([IO.Path]::GetFileName($filename) -ne $filename -or $filename.Contains(':') -or $seen.ContainsKey($package.name)) {
        throw "Invalid or duplicate offline package: $filename"
    }
    $seen[$package.name] = $true
    $file = Get-Item -LiteralPath (Join-Path $payloadRoot "apks/$filename")
    if ($file.PSIsContainer -or $file.Length -ne $package.bytes -or $file.Length -le 0) {
        throw "Offline package size does not match the manifest: $filename"
    }
}
Write-Output "OFFLINE_PAYLOAD=passed; packages=$($packages.Count); resize2fs=included"
