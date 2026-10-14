param([Parameter(Mandatory=$true)][string]$VhdPath,[switch]$Prepare,[ValidateRange(1,2)][int]$Count=1)
$ErrorActionPreference='Stop'
$path=[IO.Path]::GetFullPath($VhdPath)
$tool=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$scope=Join-Path $tool 'work'
if (-not $path.StartsWith($scope+'\',[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($path) -ne 'media.vhd') { throw 'Only owned VHD volume setup/query is allowed' }
$item=Get-Item -LiteralPath $path
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected VHD file' }
$image=Get-DiskImage -ImagePath $path -ErrorAction Stop
if (-not $image.Attached) { throw 'Owned VHD is not attached' }
$disks=@($image | Get-Disk -ErrorAction Stop)
if ($disks.Count -ne 1) { throw 'Owned VHD disk mapping is ambiguous' }
$d=$disks[0]
if ([string]$d.BusType -ne 'File Backed Virtual' -and [string]$d.BusType -ne 'FileBackedVirtual') { throw 'Not a file-backed virtual disk' }
if ($d.IsBoot -or $d.IsSystem -or $d.Size -ne 134217728 -or $d.LogicalSectorSize -ne 512) { throw 'Unexpected owned test VHD capabilities' }
if ($Prepare) {
    if ([IO.Path]::GetFileName([IO.Path]::GetDirectoryName($path)) -notmatch '^volume-lock-[0-9a-f]{32}$' -or [string]$d.PartitionStyle -ne 'RAW') { throw 'Only a new blank lock-test VHD may be initialized' }
    $initialized=Initialize-Disk -InputObject $d -PartitionStyle GPT -PassThru -ErrorAction Stop
    $created=@()
    if ($Count -eq 2) { $created += New-Partition -DiskNumber $initialized.Number -Size 50331648 -ErrorAction Stop }
    $created += New-Partition -DiskNumber $initialized.Number -UseMaximumSize -ErrorAction Stop
    foreach ($partition in $created) { $null=Format-Volume -Partition $partition -FileSystem NTFS -NewFileSystemLabel 'OXP_MEDIA_LOCK' -Confirm:$false -Force -ErrorAction Stop }
}
$parts=@(Get-Partition -DiskNumber $d.Number -ErrorAction Stop)
if (@($parts | Where-Object { $_.IsBoot -or $_.IsSystem }).Count) { throw 'Protected VHD partition found' }
$volumes=@($parts | Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.FileSystemType -eq 'NTFS' } | ForEach-Object { if ($_.FileSystemLabel -ne 'OXP_MEDIA_LOCK') { throw 'Foreign VHD test volume' }; [string]$_.Path })
if ($volumes.Count -ne $Count) { throw 'Unexpected owned NTFS volume count' }
[pscustomobject]@{DiskNumber=[int]$d.Number;Size=[long]$d.Size;Paths=$volumes} | ConvertTo-Json -Compress
