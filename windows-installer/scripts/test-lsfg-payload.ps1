$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path $PSScriptRoot -Parent
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('oxp3-lsfg-package-' + [guid]::NewGuid().ToString('N'))
$check = Join-Path $PSScriptRoot 'check-lsfg-payload.ps1'
try {
    foreach ($relative in 'components/options.json','components/catalog.json','components/lsfg-vk-release.json','cache/integration/manifest.json') {
        $target = Join-Path $fixture $relative
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceRoot $relative) -Destination $target
    }
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'cache/integration/lsfg-vk') -Destination (Join-Path $fixture 'cache/integration/lsfg-vk') -Recurse
    & $check -ProjectRoot $fixture -ArchiveRoot $sourceRoot
    $path = Join-Path $fixture 'cache/integration/manifest.json'
    $original = [IO.File]::ReadAllText($path)
    foreach ($case in 'wrong-owner','wrong-version','missing-member') {
        $value = $original | ConvertFrom-Json
        if ($case -eq 'wrong-owner') { $value.'lsfg-vk'.files[0].user = $true }
        if ($case -eq 'wrong-version') { $value.'lsfg-vk'.version = '0.12.8' }
        if ($case -eq 'missing-member') { $value.'lsfg-vk'.files = @($value.'lsfg-vk'.files | Select-Object -Skip 1) }
        [IO.File]::WriteAllText($path, ($value | ConvertTo-Json -Depth 20))
        $rejected = $false
        try { & $check -ProjectRoot $fixture -ArchiveRoot $sourceRoot } catch { $rejected = $true }
        if (!$rejected) { throw "Production LSFG-VK package check accepted $case" }
    }
    [IO.File]::WriteAllText($path, $original)
    $value = $original | ConvertFrom-Json
    $file = Join-Path $fixture ('cache/integration/' + $value.'lsfg-vk'.files[0].source)
    [IO.File]::WriteAllText($file, 'corrupt fixture')
    $rejected = $false
    try { & $check -ProjectRoot $fixture -ArchiveRoot $sourceRoot } catch { $rejected = $true }
    if (!$rejected) { throw 'Production LSFG-VK package check accepted changed bytes' }
    Write-Output 'PASS: LSFG-VK production package checks reject wrong owner/version, missing member and altered payload.'
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    if (!$resolved.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture path' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
