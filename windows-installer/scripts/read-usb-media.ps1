param([Parameter(Mandatory=$true)][string]$SourcePath)
$ErrorActionPreference='Stop'
$source=[IO.Path]::GetFullPath($SourcePath)
if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or $source -notmatch '^[A-Za-z]:\\') { throw 'A local source image is required' }
$partitions=@(Get-Partition -DriveLetter $source.Substring(0,1) -ErrorAction Stop)
$sourceNumbers=@($partitions.DiskNumber | Sort-Object -Unique)
if ($sourceNumbers.Count -ne 1) { throw 'Source volume does not map to one basic disk' }
$disks=@(Get-Disk -ErrorAction Stop | ForEach-Object {
    $d=$_
    foreach ($name in @('IsBoot','IsSystem','IsOffline','IsReadOnly','LogicalSectorSize','Size','BusType','Number')) {
        if ($null -eq $d.$name) { throw "Required disk metadata missing: $name" }
    }
    $parts=@()
    if ([string]$d.PartitionStyle -ne 'RAW') {
        $parts=@(Get-Partition -DiskNumber $d.Number -ErrorAction Stop | ForEach-Object {
            $p=$_
            if ($null -eq $p.IsBoot -or $null -eq $p.IsSystem) { throw 'Partition protection metadata missing' }
            [pscustomobject]@{ Number=[int]$p.PartitionNumber; Guid=[string]$p.Guid; Offset=[long]$p.Offset; Size=[long]$p.Size; Type=[string]$p.Type; IsBoot=[bool]$p.IsBoot; IsSystem=[bool]$p.IsSystem; AccessPaths=@($p.AccessPaths | ForEach-Object {[string]$_}) }
        })
    }
    [pscustomobject]@{ Number=[int]$d.Number; UniqueId=([string]$d.UniqueId).Trim(); Serial=([string]$d.SerialNumber).Trim(); Model=[string]$d.FriendlyName; Size=[long]$d.Size; SectorSize=[int]$d.LogicalSectorSize; Bus=[string]$d.BusType; Style=[string]$d.PartitionStyle; IsBoot=[bool]$d.IsBoot; IsSystem=[bool]$d.IsSystem; IsOffline=[bool]$d.IsOffline; IsReadOnly=[bool]$d.IsReadOnly; Health=[string]$d.HealthStatus; Operational=@($d.OperationalStatus | ForEach-Object {[string]$_}); Partitions=$parts }
})
if (@($disks | Where-Object Number -eq $sourceNumbers[0]).Count -ne 1) { throw 'Source disk is absent or ambiguous' }
[pscustomobject]@{Schema=1;SourceDiskNumber=[int]$sourceNumbers[0];Disks=$disks} | ConvertTo-Json -Depth 8 -Compress
