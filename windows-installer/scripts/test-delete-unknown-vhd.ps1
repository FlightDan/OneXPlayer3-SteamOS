# Exercise the production deletion script against one newly created Linux-type
# partition. Only disk inventory bus metadata is adapted for this owned VHD.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskDirectory = Join-Path $taskRoot ('work/delete-unknown-vhd-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskDirectory | Out-Null
$taskVhd = Join-Path $taskDirectory 'fixture.vhdx'
$taskMounted = $false
try {
    New-VHD -Path $taskVhd -Dynamic -SizeBytes 512MB | Out-Null
    Mount-VHD -Path $taskVhd -NoDriveLetter | Out-Null
    $taskMounted = $true
    $taskBound = @(Get-DiskImage -ImagePath $taskVhd | Storage\Get-Disk)
    if ($taskBound.Count -ne 1 -or $taskBound[0].IsBoot -or $taskBound[0].IsSystem -or $taskBound[0].Size -ne 512MB) { throw 'Unexpected test disk.' }
    $taskNumber = $taskBound[0].Number
    Initialize-Disk -Number $taskNumber -PartitionStyle GPT | Out-Null
    $taskKeep = New-Partition -DiskNumber $taskNumber -Offset 32MB -Size 128MB
    $taskVolume = Format-Volume -Partition $taskKeep -FileSystem NTFS -NewFileSystemLabel 'DELETE_TEST_KEEP' -Confirm:$false
    $taskSentinel = $taskVolume.Path + 'preserved.txt'
    [IO.File]::WriteAllText($taskSentinel, 'retain the other partition')
    $taskLinux = New-Partition -DiskNumber $taskNumber -Offset 160MB -Size 64MB -GptType '{0FC63DAF-8483-4772-8E79-3D69D8477DE4}'
    function Get-Disk {
        [CmdletBinding()]param([int]$Number)
        $bound = @(Get-DiskImage -ImagePath $taskVhd | Storage\Get-Disk)
        if ($bound.Count -ne 1 -or $bound[0].Number -ne $taskNumber -or $bound[0].Size -ne 512MB -or $bound[0].IsBoot -or $bound[0].IsSystem -or [string]$bound[0].BusType -notin @('File Backed Virtual','FileBackedVirtual')) { throw 'Owned VHD binding changed.' }
        if ($PSBoundParameters.ContainsKey('Number') -and $Number -ne $taskNumber) { throw 'Outside test disk.' }
        $inventory = $bound[0] | Select-Object *
        $inventory.BusType = 'NVMe'
        $inventory
    }
    $taskSnapshot = (& (Join-Path $PSScriptRoot 'read-disks.ps1')) -join [Environment]::NewLine
    $taskSnapshot | Set-Content (Join-Path $taskDirectory 'snapshot.json')
    $taskTarget = @((($taskSnapshot | ConvertFrom-Json)[0]).partitions | Where-Object { [guid]$_.guid -eq [guid]$taskLinux.Guid })
    if ($taskTarget.Count -ne 1 -or $taskTarget[0].deletionAllowed -ne $true) { throw 'Linux partition was not offered for deletion.' }
    $taskRequest = Join-Path $taskDirectory 'request.json'
    @{Snapshot=$taskSnapshot;Example=$false;Disk=$taskNumber;Start=$taskLinux.Offset;Language='en-US'} | ConvertTo-Json -Depth 10 | Set-Content $taskRequest
    & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $taskRequest -ValidateOnly
    & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $taskRequest
    if (@(Get-Partition -DiskNumber $taskNumber | Where-Object { [guid]$_.Guid -eq [guid]$taskLinux.Guid }).Count -ne 0 -or [IO.File]::ReadAllText($taskSentinel) -ne 'retain the other partition') { throw 'Deletion or preservation failed.' }
    @{passed=$true;vhd=$taskVhd;removedGuid=$taskLinux.Guid;otherPartitionDataPreserved=$true;scope='Production delete script; only inventory bus adapted for a bound disposable VHD. No physical disk writes.'} | ConvertTo-Json | Set-Content (Join-Path $taskDirectory 'result.json')
    Write-Output "Passed actual unknown-partition deletion: $taskDirectory"
} finally {
    if ($taskMounted) { Dismount-VHD -Path $taskVhd }
}
