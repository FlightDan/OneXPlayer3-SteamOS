param([string]$Stamp = (Get-Date -Format 'yyyyMMdd-HHmmss'), [ValidateSet('zip','tar')][string]$Format = 'tar', [Alias('PublicBeta')][switch]$PublicRelease, [string]$SourceCommit = '')
$ErrorActionPreference = 'Stop'
if ($Stamp -notmatch '^\d{8}-\d{6}$') { throw 'Invalid package version' }
if ($PublicRelease -and $SourceCommit -notmatch '^[0-9a-f]{40}$') { throw 'A public release must identify its source commit.' }
$projectRoot = Split-Path $PSScriptRoot -Parent
$releasePath = Join-Path $projectRoot 'components/release.json'
$release = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
$validStable = $release.version -match '^\d+\.\d+\.\d+$' -and $release.channel -eq 'stable'
$validBeta = $release.version -match '^\d+\.\d+\.\d+-beta$' -and $release.channel -eq 'beta'
if ($release.schema -ne 1 -or !($validStable -or $validBeta)) { throw 'Invalid integration release metadata' }
$integrationManifest = Get-Content -LiteralPath (Join-Path $projectRoot 'cache/integration/manifest.json') -Raw | ConvertFrom-Json
$wifiFiles = @($integrationManifest.wifi.files | Where-Object { $_.target -eq 'usr/lib/firmware/iwlwifi-sc-a0-fm-c0-c106.ucode' })
if ($wifiFiles.Count -ne 1) { throw 'This package must retain the accepted Wi-Fi c106 firmware.' }
foreach ($suffix in 'iml.sfi','pci.ddc','pci.sfi','usb.ddc','usb.sfi') {
    $entry = @($integrationManifest.wifi.files | Where-Object { $_.target -eq "usr/lib/firmware/intel/ibt-00a0-0291-$suffix" })
    if ($entry.Count -ne 1 -or !(Test-Path -LiteralPath (Join-Path $projectRoot ('cache/integration/' + $entry[0].source)))) { throw "BE201 Bluetooth firmware missing: $suffix" }
}
$wifiSource = Join-Path $projectRoot ('cache/integration/' + $wifiFiles[0].source)
if (!(Test-Path -LiteralPath $wifiSource -PathType Leaf)) { throw 'Wi-Fi c106 payload is missing.' }
& (Join-Path $PSScriptRoot 'validate-offline-payload.ps1') -ProjectRoot $projectRoot
& (Join-Path $PSScriptRoot 'validate-windows-reboot-payload.ps1') -ProjectRoot $projectRoot
$destination = Join-Path $projectRoot "dist/$stamp/Oxp3Installer"
if (Test-Path -LiteralPath $destination) { throw 'Use a fresh package stamp; an existing package must not be overwritten.' }
New-Item -ItemType Directory -Force $destination | Out-Null
function Copy-PackageTree([string]$source, [string]$relative) {
    $target = Join-Path $destination $relative
    New-Item -ItemType Directory -Force $target | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
        $_.FullName -notmatch '(^|[\\/])(__pycache__|node_modules)([\\/]|$)' -and
        $_.Extension -notin @('.pyc','.pdb') -and
        !($relative -eq 'cache/plugins' -and $_.FullName -match '([\\/])protondb([\\/])' -and $_.Name -match '\.zip$' -and $_.Name -ne 'protondb-1.3.4.zip') -and
        !($relative -eq 'cache/plugins' -and $_.FullName -match '([\\/])hltb([\\/])' -and $_.Name -match '\.zip$' -and $_.Name -ne 'hltb-2.0.12.zip') -and
        !($relative -eq 'cache/plugins' -and $_.FullName -match '([\\/])tabmaster([\\/])' -and $_.Name -match '\.zip$')
    }) {
        if ($PublicRelease -and $relative -eq 'docs' -and $item.Name -match '^(early-repair-audit-20261014|final-installer-validation|five-repairs-20261014|g3e-repair-status|permission-regression-20261014)\.json$') { continue }
        if ($relative -eq 'scripts' -and $item.Name -eq 'collect-desktop-runtime.py') { continue }
        $relativeFile = [IO.Path]::GetRelativePath($source, $item.FullName)
        $fileTarget = Join-Path $target $relativeFile
        New-Item -ItemType Directory -Force (Split-Path $fileTarget -Parent) | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $fileTarget
    }
}
Copy-PackageTree (Join-Path $projectRoot 'app/bin/Debug/net10.0-windows') 'app/bin/Debug/net10.0-windows'
Copy-PackageTree (Join-Path $projectRoot 'runtime/qemu-min') 'runtime/qemu-min'
Copy-PackageTree (Join-Path $projectRoot 'runtime/alpine/boot') 'runtime/alpine/boot'
Copy-PackageTree (Join-Path $projectRoot 'runtime/archive') 'runtime/archive'
Copy-PackageTree (Join-Path $projectRoot 'runtime/aria2') 'runtime/aria2'
Copy-PackageTree (Join-Path $projectRoot 'runtime/desync') 'runtime/desync'
Copy-PackageTree (Join-Path $projectRoot 'runtime/console') 'runtime/console'
$dotnet = Join-Path $projectRoot 'runtime/dotnet'
New-Item -ItemType Directory -Force (Join-Path $destination 'runtime/dotnet') | Out-Null
Copy-Item -LiteralPath (Join-Path $dotnet 'dotnet.exe') -Destination (Join-Path $destination 'runtime/dotnet/dotnet.exe')
Copy-PackageTree (Join-Path $dotnet 'host/fxr') 'runtime/dotnet/host/fxr'
Copy-PackageTree (Join-Path $dotnet 'shared/Microsoft.NETCore.App') 'runtime/dotnet/shared/Microsoft.NETCore.App'
Copy-PackageTree (Join-Path $dotnet 'shared/Microsoft.WindowsDesktop.App') 'runtime/dotnet/shared/Microsoft.WindowsDesktop.App'
foreach ($name in 'LICENSE.txt','ThirdPartyNotices.txt') {
    if (Test-Path (Join-Path $dotnet $name)) { Copy-Item -LiteralPath (Join-Path $dotnet $name) -Destination (Join-Path $destination "runtime/dotnet/$name") }
}
New-Item -ItemType Directory -Force (Join-Path $destination 'runtime/payload/apks'),(Join-Path $destination 'cache'),(Join-Path $destination 'guest'),(Join-Path $destination 'scripts') | Out-Null
$packages = Get-Content (Join-Path $projectRoot 'runtime/payload/packages.json') -Raw | ConvertFrom-Json
foreach ($package in $packages) {
    $filename = "$($package.name)-$($package.version).apk"
    if ([IO.Path]::GetFileName($filename) -ne $filename) { throw 'Unsafe package filename' }
    Copy-Item -LiteralPath (Join-Path $projectRoot "runtime/payload/apks/$filename") -Destination (Join-Path $destination "runtime/payload/apks/$filename")
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'runtime/payload/packages.json') -Destination (Join-Path $destination 'runtime/payload/packages.json')
Copy-Item -LiteralPath (Join-Path $projectRoot 'cache/alpine-virt-3.23.6-x86_64.iso') -Destination (Join-Path $destination 'cache/alpine-virt-3.23.6-x86_64.iso')
foreach ($name in 'common.sh','smoke.sh','build.sh','verify.sh','inspect.sh','preview.py','preview-launcher.py','install-preview-console.sh','resources.py','media_layer.py','test_media_layer.py','install_session.py','test_install_session.py','install-session-test.sh','intent_store.py','test_intent.py','mount-intent.sh','intent-hardstop.py','session-intent-interrupt.sh','session-intent-recover.sh','layout.py','handoff.py','test_handoff.py','handoff-metadata.sh','handoff-binding.sh','partition-test.sh','deployment-test.sh','deployment.py','deployment-fixture.py','test_deployment_plan.py','deployment-hardstop.py','deployment-interrupt.sh','deployment-recovery.sh','plugin-test.sh','plugin-test.py','refine-preview.sh') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name")
}
foreach ($name in 'fs_metadata.py','test_fs_metadata.py','journal-migration-check.py','journal-migration-check.sh') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name")
}
foreach ($name in 'installer_ui.py','ui_model.py','ui_backend.py','test_ui_model.py','install-ui-files.sh','install-firstboot-library.sh','component_choice.py','test_component_choice.py','bootstrap_payload.py','ui-bootstrap-seed.sh') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name")
}
foreach ($name in 'ui-installed-check.py','ui-installed-check.sh') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name")
}
foreach ($name in 'ui-cancelled-check.py','ui-cancelled-check.sh') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name")
}
foreach ($name in 'hdr-test.py','hdr-test.sh','shared-state-test.py','shared-state-test.sh','firstboot-prepare.py','firstboot-prepare.sh','firstboot-verify.sh') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name")
}
Copy-PackageTree (Join-Path $projectRoot 'components') 'components'
Copy-Item -LiteralPath $releasePath -Destination (Join-Path $destination 'release.json')
@{ schema = 1; release = $release; build_id = $Stamp; source_commit = $SourceCommit; package_channel = $(if ($PublicRelease) { if ($release.channel -eq 'stable') { 'public-release' } else { 'public-beta' } } else { 'development' }) } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'build-info.json') -Encoding utf8
Copy-PackageTree (Join-Path $projectRoot 'cache/integration') 'cache/integration'
Copy-PackageTree (Join-Path $projectRoot 'cache/plugins') 'cache/plugins'
foreach ($name in 'secret-input-check.sh','refind-image.sh','refind-image.py','integration.sh','integration-image.py','integration-check.sh','integration-delta-check.sh','integration-verify.sh','integration-verify.py','upgrade-source.sh','upgrade-source.py','physical-readiness.sh','physical-readiness.py','resize-prepared.sh','resize_prepared.py') { Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name") }
foreach ($name in 'offload_mounts.py','test_offload_mounts.py') { Copy-Item -LiteralPath (Join-Path $projectRoot "guest/$name") -Destination (Join-Path $destination "guest/$name") }
foreach ($resource in 'waydroid','oxp3-controls','hdr') {
    $source = Join-Path $projectRoot "cache/components/$resource"
    $target = Join-Path $destination "cache/components/$resource"
    New-Item -ItemType Directory -Force $target | Out-Null
    $profile = Get-Content -LiteralPath (Join-Path $source 'profile.json') -Raw | ConvertFrom-Json
    $resourceFiles = @('profile.json', $profile.archive)
    if ($resource -eq 'waydroid') { $resourceFiles += @($profile.source_archive, 'intel-ibt-kernel-calls.patch') }
    foreach ($name in $resourceFiles) {
        if ([IO.Path]::GetFileName($name) -ne $name) { throw 'Unsafe resource path' }
        Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $target $name)
    }
}
foreach ($item in @(@('decky','PluginLoader'), @('steamgriddb','steamgriddb-1.8.1.zip'), @('protondb','protondb-1.3.4.zip'), @('tabmaster','tabmaster-2.15.1+oxp3.1.zip'), @('hltb','hltb-2.0.12.zip'))) {
    $directory = Join-Path $destination "cache/plugins/$($item[0])"
    New-Item -ItemType Directory -Force $directory | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot "cache/plugins/$($item[0])/$($item[1])") -Destination $directory
}
foreach ($name in 'read-disks.ps1','format-remaining.ps1','partition-delete-policy.ps1','delete-partition.ps1','read-usb-media.ps1','vhd-test-volumes.ps1','partition-vhd-lab.ps1','test-partition-deployment.ps1','test-installation-wizard.ps1','test-installation-recovery.ps1','test-image-download.ps1','test-startup-policy.ps1','test-refind-installation.ps1','capture-refind-installed-menu.py','build-refind-theme.py','render-refind-steam.cjs') {
    Copy-Item -LiteralPath (Join-Path $projectRoot "scripts/$name") -Destination (Join-Path $destination "scripts/$name")
}
foreach ($name in 'SteamOSInstaller.exe','Launch.cmd','README.md','IMPLEMENTATION_STATUS.md') { Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination (Join-Path $destination $name) }
Copy-PackageTree (Join-Path $projectRoot 'licenses') 'licenses'
Copy-PackageTree (Join-Path $projectRoot 'docs') 'docs'
# Development test ZIPs need the same current task dependencies as beta ZIPs.
# Historical explicit lists alone omit newer tasks such as capacity-check.
Copy-PackageTree (Join-Path $projectRoot 'guest') 'guest'
Copy-PackageTree (Join-Path $projectRoot 'scripts') 'scripts'
if ($PublicRelease) {
    $workspaceRoot = Split-Path $projectRoot -Parent
    foreach ($name in @('LICENSE','THIRD_PARTY_NOTICES.md','ROADMAP.md','GIT_WORKSPACE.md')) {
        Copy-Item -LiteralPath (Join-Path $workspaceRoot $name) -Destination (Join-Path $destination $name)
    }
    $releaseDoc = 'docs/RELEASE_' + $release.version.Replace('-', '_').ToUpperInvariant() + '.md'
    Copy-Item -LiteralPath (Join-Path $projectRoot $releaseDoc) -Destination (Join-Path $destination 'READ_FIRST.md')
    $readFirst = Join-Path $destination 'READ_FIRST.md'
    $readFirstContent = [IO.File]::ReadAllText($readFirst).Replace('(../IMPLEMENTATION_STATUS.md)', '(IMPLEMENTATION_STATUS.md)').Replace('(INSTALLATION_GUIDE.md)', '(docs/INSTALLATION_GUIDE.md)').Replace('(screenshots/', '(docs/screenshots/').Replace('(REGRESSION_', '(docs/REGRESSION_')
    [IO.File]::WriteAllText($readFirst, $readFirstContent, [Text.UTF8Encoding]::new($false))
    # The installed package uses the existing flat runtime layout, while the
    # GitHub source keeps windows-installer as a subdirectory.
    $publicDocs = @((Join-Path $destination 'README.md'), (Join-Path $destination 'THIRD_PARTY_NOTICES.md')) + @(Get-ChildItem (Join-Path $destination 'docs') -Filter '*.md' -File | ForEach-Object FullName)
    foreach ($document in $publicDocs) {
        $content = [IO.File]::ReadAllText($document)
        $content = $content.Replace('(../ROADMAP.md)', '(ROADMAP.md)').Replace('(../GIT_WORKSPACE.md)', '(GIT_WORKSPACE.md)')
        $content = $content.Replace('(../../ROADMAP.md)', '(../ROADMAP.md)').Replace('(../../GIT_WORKSPACE.md)', '(../GIT_WORKSPACE.md)').Replace('(../../LICENSE)', '(../LICENSE)').Replace('(../../THIRD_PARTY_NOTICES.md)', '(../THIRD_PARTY_NOTICES.md)')
        $content = $content.Replace('(windows-installer/', '(')
        [IO.File]::WriteAllText($document, $content, [Text.UTF8Encoding]::new($false))
    }
} else {
@'
Local development package. Do not publish as a completed installer.
No SteamOS or Android system image, private research evidence, credentials or user configuration is included.
QEMU, its Windows DLL dependencies, EDK2, Alpine packages, 7-Zip and .NET sources/licenses require a complete redistribution inventory before a public release.
No WSL2, SDK, Node.js or installed VM software is needed to run the prepared app.
'@ | Set-Content -LiteralPath (Join-Path $destination 'DEVELOPMENT_PACKAGE.txt') -Encoding utf8
}
$prefix = if ($PublicRelease) { 'oxp3-steamos-installer' } else { 'oxp3-development' }
$archive = Join-Path $projectRoot "dist/$prefix-$($release.version)-$stamp.$Format"
& 'C:\Program Files\7-Zip\7z.exe' a "-t$Format" $archive (Join-Path $destination '*') | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) { throw 'Package creation failed' }
Get-Item $archive | Select-Object FullName,Length
Write-Output "Prepared folder: $destination"


