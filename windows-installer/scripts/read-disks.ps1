$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'partition-delete-policy.ps1')
$Error.Clear()
$diskSnapshots = @(Get-Disk -ErrorAction Stop)
if ($Error.Count -gt 0) { throw "Disk query failed: $($Error[0])" }
# Enumerate once. A per-disk Get-Partition query throws ObjectNotFound for an
# empty disk/card reader, even though the remaining devices are readable.
$partitionSnapshots = @(Get-Partition -ErrorAction Stop)
$disks = @($diskSnapshots | ForEach-Object {
    $disk = $_
    $diskPartitions = @($partitionSnapshots | Where-Object { $_.DiskNumber -eq $disk.Number })
    $partitionReadError = ''
    if ($null -ne $disk.NumberOfPartitions -and $diskPartitions.Count -ne $disk.NumberOfPartitions) {
        $partitionReadError = 'Partition inventory changed or is incomplete; refresh disks.'
    }
    $partitions = @($diskPartitions | ForEach-Object {
        $partition = $_
        $volume = $partition | Get-Volume -ErrorAction SilentlyContinue
        $deletionReason = Get-PartitionDeletionBlockReason $disk $partition $volume
        [pscustomobject]@{
            number = $partition.PartitionNumber; guid = [string]$partition.Guid; offset = $partition.Offset; size = $partition.Size
            type = $partition.Type; gptType = [string]$partition.GptType; letter = [string]$partition.DriveLetter
            isBoot = $partition.IsBoot; isSystem = $partition.IsSystem; isHidden = $partition.IsHidden
            deletionAllowed = ($deletionReason -eq ''); deletionBlockReason = $deletionReason
            nativeUnrecognizedSafe = ($partition.NativeUnrecognizedSafe -eq $true)
            filesystem = [string]$volume.FileSystemType; label = [string]$volume.FileSystemLabel
            free = if ($null -ne $volume) { $volume.SizeRemaining } else { $null }
        }
    })
    [pscustomobject]@{ number = $disk.Number; guid = [string]$disk.Guid; serial = ([string]$disk.SerialNumber).Trim(); sectorSize = $disk.LogicalSectorSize; model = $disk.FriendlyName; size = $disk.Size
        style = [string]$disk.PartitionStyle; bus = [string]$disk.BusType; isBoot = $disk.IsBoot
        isSystem = $disk.IsSystem; isOffline = $disk.IsOffline; isReadOnly = $disk.IsReadOnly; partitionReadError = $partitionReadError; partitions = $partitions }
})
ConvertTo-Json -InputObject $disks -Depth 6
