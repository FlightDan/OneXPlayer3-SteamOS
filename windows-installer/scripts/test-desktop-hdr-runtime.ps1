$ErrorActionPreference = 'Stop'
$validator = Join-Path $PSScriptRoot 'validate-desktop-hdr-runtime.ps1'
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('oxp3-hdr-runtime-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null

function Add-TarFile($Writer, [string]$Name, [byte[]]$Content) {
    $entry = [System.Formats.Tar.UstarTarEntry]::new([System.Formats.Tar.TarEntryType]::RegularFile, $Name)
    $entry.Mode = [IO.UnixFileMode]$(if ($Name.StartsWith('bin/')) { 493 } else { 420 })
    $entry.DataStream = [IO.MemoryStream]::new($Content)
    $Writer.WriteEntry($entry)
}

function Add-TarLink($Writer, [string]$Name, [string]$Target) {
    $link = [System.Formats.Tar.UstarTarEntry]::new([System.Formats.Tar.TarEntryType]::SymbolicLink, $Name)
    $link.LinkName = $Target
    $Writer.WriteEntry($link)
}

function New-RuntimeArchive([string]$Path, [string]$Frontend, [string]$KWin,
    [switch]$StaleSoname, [switch]$WrongSonameTarget, [switch]$CaseMismatchSonameTarget,
    [switch]$OldPresentationRenderer) {
    $stream = [IO.File]::Create($Path)
    try {
        $writer = [System.Formats.Tar.TarWriter]::new($stream, [System.Formats.Tar.TarEntryFormat]::Pax, $true)
        try {
            Add-TarFile $writer 'bin/oxp3-mapped-hdr-control' ([Text.Encoding]::Unicode.GetBytes("$Frontend X2MINI_HDR_TRIAL_475_700_V1"))
            Add-TarFile $writer 'lib/libkwin.so.6.7.3' ([Text.Encoding]::Unicode.GetBytes("$KWin X2MINI_HDR_TRIAL_475_700_V1"))
            $renderer = 'X2MINI_HDR_TRIAL_475_700_V1 HDR10 renderer FIRST_PRESENT_OK'
            if (!$OldPresentationRenderer) { $renderer += ' HDR_TRIAL_PRESENT_WAIT_V2' }
            Add-TarFile $writer 'bin/oxp3-hdr-pattern' ([Text.Encoding]::ASCII.GetBytes($renderer))
            if ($StaleSoname) {
                Add-TarFile $writer 'lib/libkwin.so.6' ([Text.Encoding]::ASCII.GetBytes('ONE-NETBOOK ONEXPLAYER 3'))
            } elseif ($WrongSonameTarget) {
                Add-TarFile $writer 'lib/old-kwin.so' ([Text.Encoding]::ASCII.GetBytes('ONE-NETBOOK ONEXPLAYER 3'))
                Add-TarLink $writer 'lib/libkwin.so.6' 'old-kwin.so'
            } elseif ($CaseMismatchSonameTarget) {
                Add-TarFile $writer 'lib/LIBKWIN.SO.6.7.3' ([Text.Encoding]::ASCII.GetBytes('ONE-NETBOOK ONEXPLAYER 3'))
                Add-TarLink $writer 'lib/libkwin.so.6' 'LIBKWIN.SO.6.7.3'
            } else {
                Add-TarLink $writer 'lib/libkwin.so.6' 'libkwin.so.6.7.3'
            }
            Add-TarLink $writer 'lib/libkwin.so' 'libkwin.so.6'
        } finally { $writer.Dispose() }
    } finally { $stream.Dispose() }
}

try {
    $marker = 'OXP3_GAMMA22_POLICY_EDID_ONLY_V2'
    $good = Join-Path $temporary 'good.tar'
    New-RuntimeArchive $good "frontend $marker" "KWin $marker"
    & $validator -RuntimePath $good

    $maintenance7 = Join-Path $temporary 'maintenance7-renderer.tar'
    New-RuntimeArchive $maintenance7 "frontend $marker HDR_TRIAL_PRESENT_WAIT_V2" "KWin $marker HDR_TRIAL_PRESENT_WAIT_V2" -OldPresentationRenderer
    $rejected = $false
    try { & $validator -RuntimePath $maintenance7 } catch { $rejected = $_.Exception.Message -like '*presentation completion marker*' }
    if (!$rejected) { throw 'The old maintenance.7 queued-only renderer was not rejected.' }

    $old = Join-Path $temporary 'old.tar'
    New-RuntimeArchive $old 'OXP3 Gamma22 HDR mapping: enabled (1100/472)' 'ONE-NETBOOK ONEXPLAYER 3'
    $rejected = $false
    try { & $validator -RuntimePath $old } catch { $rejected = $_.Exception.Message -like '*EDID-only policy marker*' }
    if (!$rejected) { throw 'Old model-locked HDR runtime was not rejected.' }

    $dmi = Join-Path $temporary 'dmi.tar'
    New-RuntimeArchive $dmi "frontend $marker" "KWin $marker /sys/class/dmi/id/product_name"
    $rejected = $false
    try { & $validator -RuntimePath $dmi } catch { $rejected = $_.Exception.Message -like '*model hard gate*' }
    if (!$rejected) { throw 'DMI-gated HDR runtime was not rejected.' }

    $mixed = Join-Path $temporary 'mixed.tar'
    New-RuntimeArchive $mixed "frontend $marker" "KWin $marker" -StaleSoname
    $rejected = $false
    $failure = $null
    try { & $validator -RuntimePath $mixed } catch { $failure = $_.Exception.ToString(); $rejected = $failure -like '*KWin SONAME entry*' }
    if (!$rejected) { throw "A stale regular SONAME library was not rejected: $failure" }

    $redirected = Join-Path $temporary 'redirected.tar'
    New-RuntimeArchive $redirected "frontend $marker" "KWin $marker" -WrongSonameTarget
    $rejected = $false
    $failure = $null
    try { & $validator -RuntimePath $redirected } catch { $failure = $_.Exception.ToString(); $rejected = $failure -like '*does not resolve to the validated compositor*' }
    if (!$rejected) { throw "A redirected SONAME symlink was not rejected: $failure" }

    $caseMismatch = Join-Path $temporary 'case-mismatch.tar'
    New-RuntimeArchive $caseMismatch "frontend $marker" "KWin $marker" -CaseMismatchSonameTarget
    $rejected = $false
    $failure = $null
    try { & $validator -RuntimePath $caseMismatch } catch { $failure = $_.Exception.ToString(); $rejected = $failure -like '*does not resolve to the validated compositor*' }
    if (!$rejected) { throw "A case-mismatched SONAME symlink was not rejected: $failure" }

    Write-Output 'PASS: PowerShell package guard accepts the validated KWin alias chain and rejects old queued-only renderers, stale, redirected, or DMI-gated binaries.'
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    if (!$resolved.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test cleanup path.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
