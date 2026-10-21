param([Parameter(Mandatory=$true)][string]$RuntimePath)
$ErrorActionPreference = 'Stop'

if (!(Test-Path -LiteralPath $RuntimePath -PathType Leaf)) { throw "Desktop-HDR runtime is missing: $RuntimePath" }
$runtimeItem = Get-Item -LiteralPath $RuntimePath -Force
if ($runtimeItem.PSIsContainer) { throw 'Desktop-HDR runtime must be a regular file.' }
$ancestor = $runtimeItem
while ($null -ne $ancestor) {
    if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked desktop-HDR runtime refused.' }
    $ancestor = if ($ancestor -is [IO.DirectoryInfo]) { $ancestor.Parent } else { $ancestor.Directory }
}

if (!('Oxp3DesktopHdrByteSearch' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
public static class Oxp3DesktopHdrByteSearch
{
    public static bool Contains(byte[] data, byte[] marker)
    {
        return data.AsSpan().IndexOf(marker.AsSpan()) >= 0;
    }
}
'@
}
$byteSearch = 'Oxp3DesktopHdrByteSearch' -as [type]
$required = @('bin/oxp3-mapped-hdr-control', 'lib/libkwin.so.6.7.3', 'bin/oxp3-hdr-pattern')
$kwinBinary = 'lib/libkwin.so.6.7.3'
$kwinLinks = @('lib/libkwin.so.6', 'lib/libkwin.so')
$policyMarker = 'OXP3_GAMMA22_POLICY_EDID_ONLY_V2'
$trialMarker = 'X2MINI_HDR_TRIAL_475_700_V1'
$modelMarkers = @('/sys/class/dmi/id/sys_vendor', '/sys/class/dmi/id/product_name', 'ONE-NETBOOK', 'ONEXPLAYER 3')
$entries = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
$binaries = [Collections.Generic.Dictionary[string,byte[]]]::new([StringComparer]::Ordinal)

function Normalize-TarPath([string]$Raw, [bool]$IsDirectory) {
    if ($Raw -in @('.', './')) { return '' }
    $name = $Raw -replace '^\./', ''
    if ($IsDirectory) { $name = $name.TrimEnd('/') }
    if (!$name -or $name.StartsWith('/') -or $name.Contains('\') -or $name.Contains(':') -or $name -match '[\x00-\x1F]') {
        throw 'Unsafe desktop-HDR runtime archive path.'
    }
    $parts = $name.Split('/')
    if ($parts | Where-Object { $_ -in @('', '.', '..') }) { throw 'Unsafe desktop-HDR runtime archive path.' }
    return $name
}

function EncodedMarkers([string]$Value) {
    return @(
        [Text.Encoding]::ASCII.GetBytes($Value),
        [Text.Encoding]::Unicode.GetBytes($Value),
        [Text.Encoding]::BigEndianUnicode.GetBytes($Value)
    )
}

$stream = [IO.File]::OpenRead($runtimeItem.FullName)
try {
    $reader = [System.Formats.Tar.TarReader]::new($stream, $true)
    try {
        while ($null -ne ($entry = $reader.GetNextEntry())) {
            $entryType = $entry.EntryType.ToString()
            $isDirectory = $entryType -eq 'Directory'
            $name = Normalize-TarPath $entry.Name $isDirectory
            if (!$name) {
                if (!$isDirectory) { throw 'Unexpected root entry in desktop-HDR runtime archive.' }
                continue
            }
            if ($entries.ContainsKey($name)) { throw "Duplicate desktop-HDR runtime archive path: $name" }
            if ($entryType -notin @('RegularFile', 'V7RegularFile', 'Directory', 'SymbolicLink')) {
                throw "Special desktop-HDR runtime archive entry refused: $name ($entryType)"
            }
            $link = $null
            if ($entryType -eq 'SymbolicLink') {
                $link = $entry.LinkName
                if (!$link -or $link.StartsWith('/') -or $link.Contains('\') -or $link.Contains(':') -or $link -match '[\x00-\x1F]' -or
                    ($link.Split('/') | Where-Object { $_ -in @('', '.', '..') })) {
                    throw "External desktop-HDR runtime link refused: $name"
                }
            }
            $entries.Add($name, [pscustomobject]@{ Name=$name; Type=$entryType; Link=$link })
            if ($name -in $required) {
                if ($entryType -notin @('RegularFile', 'V7RegularFile')) { throw "Required desktop-HDR binary must be a regular file: $name" }
                if ($name.StartsWith('bin/', [StringComparison]::Ordinal) -and !([int]$entry.Mode -band 73)) { throw "Required desktop-HDR program must be executable: $name" }
                if ($entry.Length -gt 268435456) { throw "Unreasonably large desktop-HDR binary: $name" }
                $memory = [IO.MemoryStream]::new()
                try { $entry.DataStream.CopyTo($memory); $binaries.Add($name, $memory.ToArray()) }
                finally { $memory.Dispose() }
            }
        }
    } finally { $reader.Dispose() }
} finally { $stream.Dispose() }

foreach ($record in $entries.Values) {
    if ($record.Type -ne 'SymbolicLink') { continue }
    $current = $record
    $resolvedName = $record.Name
    $visited = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    while ($current.Type -eq 'SymbolicLink') {
        if (!$visited.Add($current.Name)) { throw "Cyclic desktop-HDR runtime link: $($record.Name)" }
        $parent = $resolvedName.Substring(0, [Math]::Max(0, $resolvedName.LastIndexOf('/')))
        $target = if ($parent) { "$parent/$($current.Link)" } else { $current.Link }
        if (!$entries.ContainsKey($target)) { throw "Dangling desktop-HDR runtime link: $($current.Name)" }
        $resolvedName = $target
        $current = $entries[$target]
    }
    if ($current.Type -notin @('RegularFile', 'V7RegularFile')) { throw "Desktop-HDR runtime link does not resolve to a regular file: $($record.Name)" }
    if ($record.Name -in $kwinLinks -and $resolvedName -cne $kwinBinary) {
        throw "KWin SONAME entry does not resolve to the validated compositor: $($record.Name)"
    }
}
foreach ($name in $kwinLinks) {
    if (!$entries.ContainsKey($name) -or $entries[$name].Type -ne 'SymbolicLink') {
        throw "KWin SONAME entry must be a symbolic link to the validated compositor: $name"
    }
}

foreach ($name in $required) {
    if (!$binaries.ContainsKey($name)) { throw "Desktop-HDR runtime is missing required binary: $name" }
    $data = $binaries[$name]
    $hasPolicy = $false
    foreach ($encoded in (EncodedMarkers $policyMarker)) {
        if ($byteSearch::Contains($data, $encoded)) { $hasPolicy = $true; break }
    }
    if ($name -cne 'bin/oxp3-hdr-pattern' -and !$hasPolicy) { throw "Desktop-HDR binary is missing the EDID-only policy marker: $name" }
    foreach ($modelMarker in $modelMarkers) {
        foreach ($encoded in (EncodedMarkers $modelMarker)) {
            if ($byteSearch::Contains($data, $encoded)) { throw "Desktop-HDR binary still contains an OP3 model hard gate: $name ($modelMarker)" }
        }
    }
    $hasTrial = $false
    foreach ($encoded in (EncodedMarkers $trialMarker)) {
        if ($byteSearch::Contains($data, $encoded)) { $hasTrial = $true; break }
    }
    if (!$hasTrial) { throw "Desktop-HDR binary is missing the 475/700 trial marker: $name" }
}
Write-Output 'DESKTOP_HDR_RUNTIME=passed'
