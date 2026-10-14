param([Parameter(Mandatory=$true)][string]$VhdPath,[ValidateSet('probe','format-protected','format-lock')][string]$Action='probe')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPath=[IO.Path]::GetFullPath($VhdPath)
$taskWork=Join-Path $taskRoot 'work'
$taskSettings=Join-Path $taskRoot 'workspace.json'
if (Test-Path -LiteralPath $taskSettings) { $taskWork=[IO.Path]::GetFullPath((Get-Content -LiteralPath $taskSettings -Raw | ConvertFrom-Json)) }
if (-not $taskPath.StartsWith($taskWork.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($taskPath) -ne 'media.vhd' -or
    [IO.Path]::GetFileName([IO.Path]::GetDirectoryName($taskPath)) -notmatch '^partition-deploy-[0-9a-f]{32}$') { throw 'Only isolated partition-deployment VHDs are allowed' }
$taskItem=Get-Item -LiteralPath $taskPath
if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected VHD' }
$taskImage=Get-DiskImage -ImagePath $taskPath -ErrorAction Stop
if (-not $taskImage.Attached) { throw 'Owned VHD is not attached' }
$taskDisks=@($taskImage | Get-Disk -ErrorAction Stop)
if ($taskDisks.Count -ne 1) { throw 'Ambiguous owned VHD mapping' }
$taskDisk=$taskDisks[0]
if ([string]$taskDisk.BusType -notin @('File Backed Virtual','FileBackedVirtual') -or
    $taskDisk.IsBoot -or $taskDisk.IsSystem -or $taskDisk.LogicalSectorSize -ne 512) { throw 'Not an unprotected file-backed VHD' }
$taskParts=@(Get-Partition -DiskNumber $taskDisk.Number -ErrorAction Stop)
if (@($taskParts | Where-Object { $_.IsBoot -or $_.IsSystem }).Count) { throw 'Protected test partition found' }
if ($Action -ne 'probe') {
    if ($taskDisk.Size -ne 536870912) { throw 'Formatting is restricted to the compact 512MiB fixture' }
    $taskNumbers=if ($Action -eq 'format-protected') { @(1,2) } else { @(4) }
    foreach ($taskNumber in $taskNumbers) {
        $taskPart=@($taskParts | Where-Object PartitionNumber -eq $taskNumber)
        if ($taskPart.Count -ne 1 -or $taskPart[0].Size -ne 67108864) { throw 'Wrong compact formatting range' }
        $taskFs=if ($taskNumber -eq 1) { 'FAT32' } else { 'NTFS' }
        $null=Format-Volume -Partition $taskPart[0] -FileSystem $taskFs -NewFileSystemLabel 'OXP_PART_LAB' -Confirm:$false -Force -ErrorAction Stop
        $taskVolume=Get-Volume -Partition $taskPart[0] -ErrorAction Stop
        [IO.File]::WriteAllText(($taskVolume.Path+'preserved.txt'),('OXP partition sentinel '+$taskNumber+[char]10))
    }
}
$taskVolumes=@()
foreach ($taskPart in $taskParts) {
    $taskVolume=$taskPart | Get-Volume -ErrorAction SilentlyContinue
    if ($taskVolume -and $taskVolume.Path) { $taskVolumes += [ordered]@{Number=[int]$taskPart.PartitionNumber;Path=[string]$taskVolume.Path;FileSystem=[string]$taskVolume.FileSystemType} }
}
[ordered]@{Number=[int]$taskDisk.Number;Size=[long]$taskDisk.Size;Volumes=$taskVolumes} | ConvertTo-Json -Depth 5 -Compress
