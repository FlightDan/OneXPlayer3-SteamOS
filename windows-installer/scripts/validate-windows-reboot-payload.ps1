param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$component = Join-Path $ProjectRoot 'components/windows-reboot'
$required = @('main.py', 'plugin.json', 'package.json', 'dist/index.js', 'boot.py', 'desktop.py',
    'oxp3-reboot-windows', 'oxp3-reboot-windows.desktop',
    'org.oxp3.restart-windows.policy', '49-oxp3-restart-windows.rules')
foreach ($relative in $required) {
    $path = Join-Path $component $relative
    if (!(Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -eq 0) {
        throw "Windows restart payload is missing: $relative. Rebuild the component before packaging."
    }
}
$plugin = Get-Content -LiteralPath (Join-Path $component 'plugin.json') -Raw | ConvertFrom-Json
$package = Get-Content -LiteralPath (Join-Path $component 'package.json') -Raw | ConvertFrom-Json
$catalog = Get-Content -LiteralPath (Join-Path $ProjectRoot 'components/catalog.json') -Raw | ConvertFrom-Json
$entry = @($catalog.plugins | Where-Object id -eq 'windows-reboot')
if ($plugin.name -ne 'Restart into Windows' -or @($plugin.flags).Count -ne 1 -or $plugin.flags[0] -ne 'root') {
    throw 'Windows restart must use the root flag recognized by Decky 3.2.10.'
}
if ($entry.Count -ne 1 -or $entry[0].version -ne $package.version) {
    throw 'Windows restart catalog and bundled plugin versions do not match.'
}
$desktop = Get-Content -LiteralPath (Join-Path $component 'desktop.py') -Raw
if ($desktop.Contains('--defaultno') -or !$desktop.Contains('--warningcontinuecancel')) {
    throw 'Windows restart desktop dialog must use the supported KDE confirmation command.'
}
Write-Output "WINDOWS_REBOOT_PAYLOAD=passed; version=$($package.version); files=$($required.Count)"
