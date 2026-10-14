param([string]$NodeExecutable = 'node', [string]$DependencyRoot)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$source = Join-Path $projectRoot 'components/windows-reboot'
if (!$DependencyRoot) {
    $DependencyRoot = Join-Path $source 'node_modules'
}
$dependencies = (Resolve-Path -LiteralPath $DependencyRoot).Path
foreach ($file in @('typescript/bin/tsc', 'rollup/dist/bin/rollup', '@decky/ui/package.json')) {
    if (!(Test-Path -LiteralPath (Join-Path $dependencies $file))) { throw "Missing build dependency: $file" }
}
# Build in an ignored, fresh directory. Dependencies and intermediate source maps
# stay out of the component payload shipped by the installer.
$build = Join-Path $projectRoot ('work/windows-reboot-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $build | Out-Null
foreach ($name in @('package.json', 'plugin.json', 'tsconfig.json', 'rollup.config.js', 'src')) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination $build -Recurse
}
New-Item -ItemType Junction -Path (Join-Path $build 'node_modules') -Target $dependencies | Out-Null
Push-Location $build
try {
    & $NodeExecutable (Join-Path $dependencies 'typescript/bin/tsc') --noEmit
    if ($LASTEXITCODE -ne 0) { throw 'Windows restart frontend typecheck failed' }
    & $NodeExecutable (Join-Path $dependencies 'rollup/dist/bin/rollup') -c
    if ($LASTEXITCODE -ne 0) { throw 'Windows restart frontend build failed' }
    $destination = Join-Path $source 'dist'
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $javascript = Get-Content -LiteralPath (Join-Path $build 'dist/index.js') -Raw
    $javascript = $javascript -replace '(?m)^//# sourceMappingURL=.*\r?\n?', ''
    [IO.File]::WriteAllText((Join-Path $destination 'index.js'), $javascript, [Text.UTF8Encoding]::new($false))
    & $NodeExecutable (Join-Path $source 'test_frontend.mjs')
    if ($LASTEXITCODE -ne 0) { throw 'Windows restart frontend interaction checks failed' }
    Write-Output "WINDOWS_REBOOT_FRONTEND=passed; $destination/index.js"
} finally { Pop-Location }
