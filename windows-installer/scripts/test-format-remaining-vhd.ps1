# Actual NTFS formatting only inside a newly created, uniquely named disposable VHDX.
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskDir=Join-Path $taskRoot ('work/ntfs-vhd-check-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskDir | Out-Null
$taskVhd=Join-Path $taskDir 'fixture.vhdx'
$taskMounted=$false
try {
    New-VHD -Path $taskVhd -Dynamic -SizeBytes 96GB -BlockSizeBytes 1MB -LogicalSectorSizeBytes 512 -ErrorAction Stop | Out-Null
    Mount-VHD -Path $taskVhd -NoDriveLetter | Out-Null; $taskMounted=$true
    $taskDisk=@(Get-DiskImage -ImagePath $taskVhd | Get-Disk)
    if($taskDisk.Count -ne 1 -or $taskDisk[0].IsBoot -or $taskDisk[0].IsSystem -or $taskDisk[0].Size -ne 96GB -or [string]$taskDisk[0].BusType -notin @('File Backed Virtual','FileBackedVirtual')){throw 'Not the owned disposable VHD.'}
    $taskNumber=$taskDisk[0].Number
    Initialize-Disk -Number $taskNumber -PartitionStyle GPT | Out-Null
    $taskKeep=New-Partition -DiskNumber $taskNumber -Offset 32MB -Size 512MB -GptType '{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}' -ErrorAction Stop
    $taskKeepVolume=Format-Volume -Partition $taskKeep -FileSystem NTFS -NewFileSystemLabel 'NTFS_TEST_KEEP' -Confirm:$false
    $taskSentinel=$taskKeepVolume.Path+'preserved.txt'
    [IO.File]::WriteAllText($taskSentinel,'preserve this VHD fixture data')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'format-remaining.ps1') -Destination (Join-Path $taskDir 'format-remaining.ps1')
    # Adapt only the inventory bus of this exact owned VHD for the physical-script test.
    # The production script continues to reject virtual disks in normal operation.
    $taskRead=Join-Path $PSScriptRoot 'read-disks.ps1'
    $taskAdapter=@'
$ErrorActionPreference='Stop'
$image=Get-DiskImage -ImagePath '__VHD__'
if(-not $image.Attached){throw 'Fixture detached'}
$bound=@($image|Get-Disk)
if($bound.Count -ne 1 -or $bound[0].IsBoot -or $bound[0].IsSystem -or $bound[0].Size -ne 96GB -or [string]$bound[0].BusType -notin @('File Backed Virtual','FileBackedVirtual')){throw 'Fixture binding changed'}
$data=@((& '__READ__')|ConvertFrom-Json|Where-Object number -eq $bound[0].Number)
if($data.Count -ne 1){throw 'Missing fixture inventory'}
$data[0].bus='NVMe'
ConvertTo-Json -InputObject $data -Depth 8
'@
    $taskAdapter.Replace('__VHD__',$taskVhd.Replace("'","''")).Replace('__READ__',$taskRead.Replace("'","''")) | Set-Content (Join-Path $taskDir 'read-disks.ps1')
    $taskSnapshot=& (Join-Path $taskDir 'read-disks.ps1')
    $taskRequest=Join-Path $taskDir 'format-request.json'
    @{Selection=@{Snapshot=$taskSnapshot;Example=$false;Disk=$taskNumber;Start=544MB;Capacity=64GB};Language='en-US'}|ConvertTo-Json -Depth 10|Set-Content $taskRequest
    & (Join-Path $taskDir 'format-remaining.ps1') -RequestPath $taskRequest -ValidateOnly
    & (Join-Path $taskDir 'format-remaining.ps1') -RequestPath $taskRequest
    if([IO.File]::ReadAllText($taskSentinel) -ne 'preserve this VHD fixture data'){throw 'Existing fixture data changed'}
    $taskResult=Get-Content (Join-Path $taskDir 'format-result.json') -Raw|ConvertFrom-Json
    $taskNew=@(Get-Partition -DiskNumber $taskNumber|Where-Object { [guid]$_.Guid -eq [guid]$taskResult.partitionGuid })
    $taskVolume=$taskNew[0]|Get-Volume
    if($taskNew.Count -ne 1 -or $taskResult.phase -ne 'verified' -or $taskNew[0].Offset -ne 544MB+64GB -or $taskNew[0].Offset % 4096 -ne 0 -or $taskVolume.FileSystemType -ne 'NTFS' -or $taskVolume.AllocationUnitSize -ne 4096){throw 'NTFS VHD verification failed'}
    @{passed=$true;diskFile=$taskVhd;start=$taskNew[0].Offset;bytes=$taskNew[0].Size;filesystem='NTFS';clusterBytes=4096;existingDataPreserved=$true;scope='Production format script with an inventory adapter bound to this newly created VHD; no physical disk writes.'}|ConvertTo-Json|Set-Content (Join-Path $taskDir 'result.json')
    Write-Output "Passed actual NTFS VHD check: $taskDir"
} finally { if($taskMounted){Dismount-VHD -Path $taskVhd} }
