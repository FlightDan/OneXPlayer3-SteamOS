param([Parameter(Mandatory=$true)][string]$RequestPath, [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$selection = $request.Selection
if ($selection.Example -ne $false) { throw 'Example or incomplete requests cannot format real disks.' }
# Missing placement is the legacy left-aligned request. Reject coerced strings/numbers.
$alignRight = $false
if ($selection.PSObject.Properties.Name -contains 'AlignRight') {
    if ($selection.AlignRight -isnot [bool]) { throw 'Invalid SteamOS placement choice.' }
    $alignRight = $selection.AlignRight
}
# Windows PowerShell 5.1 keeps a root JSON array as a single pipeline object.
# Parenthesize deserialization to enumerate disks before binding the target.
$expected = @(($selection.Snapshot | ConvertFrom-Json) | Where-Object { $_.number -eq $selection.Disk })
if ($expected.Count -ne 1) { throw 'Ambiguous reviewed disk.' }
$expected = $expected[0]
if ($expected.style -ne 'GPT' -or $expected.sectorSize -ne 512 -or $expected.bus -notin @('NVMe','SATA','USB','SD','MMC') -or $expected.isOffline -ne $false -or $expected.isReadOnly -ne $false -or $expected.partitionReadError) { throw 'Disk is not eligible.' }
if ([guid]$expected.guid -eq [guid]::Empty -or @($expected.partitions).Count -gt 119) { throw 'Missing disk identity or insufficient GPT entries for NTFS and SteamOS.' }
[long]$start = $selection.Start
[long]$capacity = $selection.Capacity
if ($capacity -lt 64GB -or $capacity % 1MB -ne 0 -or $start -lt 1MB -or $start % 1MB -ne 0 -or $capacity -gt $expected.size - $start) { throw 'Invalid reserved SteamOS range.' }
# Derive the entire selected gap from the snapshot; do not accept a caller-supplied format range.
[long]$cursor = 0
[long]$gapEnd = 0
$ids = @{}
$numbers = @{}
foreach ($part in @($expected.partitions | Sort-Object offset)) {
    if ([guid]$part.guid -eq [guid]::Empty -or [guid]$part.gptType -eq [guid]::Empty -or $ids.ContainsKey([string]$part.guid) -or $numbers.ContainsKey([string]$part.number)) { throw 'Invalid partition identity.' }
    $ids[[string]$part.guid] = $true; $numbers[[string]$part.number] = $true
    if ($part.offset -lt $cursor -or $part.size -le 0 -or $part.offset -gt $expected.size - $part.size) { throw 'Invalid partition layout.' }
    [long]$alignedStart = [math]::Max([long]1MB, [long]([math]::Ceiling($cursor / 1MB) * 1MB))
    [long]$alignedEnd = [math]::Floor($part.offset / 1MB) * 1MB
    if ($alignedStart -eq $start -and $alignedEnd -gt $start) { $gapEnd = $alignedEnd }
    $cursor = $part.offset + $part.size
}
if ([math]::Max([long]1MB, [long]([math]::Ceiling($cursor / 1MB) * 1MB)) -eq $start) { $gapEnd = [long]([math]::Floor($expected.size / 1MB) * 1MB) - 1MB }
[long]$formatSize = $gapEnd - $start - $capacity
[long]$reservedStart = $start
[long]$formatStart = $start + $capacity
if ($alignRight) { $reservedStart = $gapEnd - $capacity; $formatStart = $start }
if ($formatSize -lt 64MB -or $formatStart % 1MB -ne 0 -or $formatSize % 1MB -ne 0) { throw 'At least 64 MiB of aligned unallocated space must remain.' }

function Assert-CurrentLayout($NewPartition) {
    $fresh = @(((& (Join-Path $PSScriptRoot 'read-disks.ps1')) | ConvertFrom-Json) | Where-Object { $_.number -eq $selection.Disk })
    if ($fresh.Count -ne 1) { throw 'Disk missing; refresh before continuing.' }
    $fresh = $fresh[0]
    foreach ($key in @('number','guid','serial','model','size','sectorSize','style','bus','isOffline','isReadOnly')) {
        if ($null -eq $expected.$key -or [string]$expected.$key -ne [string]$fresh.$key) { throw "Disk identity changed: $key." }
    }
    if ($fresh.partitionReadError) { throw 'Incomplete partition inventory.' }
    $count = @($expected.partitions).Count
    if ($null -ne $NewPartition) { $count++ }
    if (@($fresh.partitions).Count -ne $count) { throw 'Partition layout changed; refresh before continuing.' }
    foreach ($part in $expected.partitions) {
        $same = @($fresh.partitions | Where-Object { [guid]$_.guid -eq [guid]$part.guid })
        if ($same.Count -ne 1) { throw 'Existing partition missing.' }
        foreach ($key in @('number','offset','size','gptType','letter','isBoot','isSystem','isHidden')) {
            if ($null -eq $part.$key -or [string]$part.$key -ne [string]$same[0].$key) { throw "Existing partition changed: $key." }
        }
    }
    if ($null -ne $NewPartition) {
        $same = @($fresh.partitions | Where-Object { [guid]$_.guid -eq [guid]$NewPartition.Guid })
        if ($same.Count -ne 1 -or $same[0].offset -ne $formatStart -or $same[0].size -ne $formatSize -or [guid]$same[0].gptType -ne [guid]'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7' -or $same[0].isBoot -ne $false -or $same[0].isSystem -ne $false) { throw 'New partition does not match the reviewed range.' }
    }
}
Assert-CurrentLayout $null
if ($ValidateOnly) { return }
$resultPath = Join-Path (Split-Path -Parent $RequestPath) 'format-result.json'
$result = [ordered]@{ phase='planned'; disk=$selection.Disk; start=$formatStart; size=$formatSize; clusterBytes=4096; partitionGuid=$null; alignRight=$alignRight; steamOSStart=$reservedStart; steamOSSize=$capacity }
$result | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
# No formatting of existing volumes: create only in the reviewed free remainder.
$created = New-Partition -DiskNumber $selection.Disk -Offset $formatStart -Size $formatSize -Alignment 1MB -GptType '{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}' -ErrorAction Stop
$result.partitionGuid = [string]$created.Guid; $result.phase = 'created'
$result | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
Assert-CurrentLayout $created
$bound = Get-Partition -DiskNumber $selection.Disk -PartitionNumber $created.PartitionNumber -ErrorAction Stop
if ([guid]$bound.Guid -ne [guid]$created.Guid -or $bound.Offset -ne $formatStart -or $bound.Size -ne $formatSize) { throw 'New partition changed before formatting.' }
$volume = Format-Volume -Partition $bound -FileSystem NTFS -AllocationUnitSize 4096 -NewFileSystemLabel 'Data' -Confirm:$false -ErrorAction Stop
if ([string]$volume.FileSystemType -ne 'NTFS' -or $volume.AllocationUnitSize -ne 4096 -or [string]$volume.HealthStatus -ne 'Healthy') { throw 'NTFS format verification failed. Refresh and inspect the created partition.' }
Assert-CurrentLayout $created
$bound | Add-PartitionAccessPath -AssignDriveLetter -ErrorAction Stop
Assert-CurrentLayout $created
$result.phase = 'verified'; $result | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
