$ErrorActionPreference = 'Stop'
$global:OxpInventoryTestScenario = 'normal'
function Get-Disk {
    [CmdletBinding()]param()
    foreach ($number in 0, 2) {
        [pscustomobject]@{ Number=$number; NumberOfPartitions= $(if ($number -eq 0) { 1 } else { 0 });
            Guid=[guid]::NewGuid().ToString(); Size=256GB; LogicalSectorSize=512; FriendlyName='Fixture';
            PartitionStyle='GPT'; BusType='NVMe'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false }
    }
}
function Get-Partition {
    [CmdletBinding()]param([int]$DiskNumber)
    if ($PSBoundParameters.ContainsKey('DiskNumber')) { throw 'Per-disk empty query regression' }
    if ($global:OxpInventoryTestScenario -eq 'error') { throw 'Access denied fixture' }
    if ($global:OxpInventoryTestScenario -eq 'missing') { return }
    [pscustomobject]@{ DiskNumber=0; PartitionNumber=1; Guid=[guid]::NewGuid().ToString(); Offset=1MB; Size=128GB;
        Type='Basic'; GptType='{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}'; DriveLetter='';
        IsBoot=$false; IsSystem=$false; IsHidden=$false }
}
function Get-Volume { [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$Partition) process { } }
$reader=Join-Path $PSScriptRoot 'read-disks.ps1'
$normal = (& $reader) | ConvertFrom-Json
if ($normal.Count -ne 2 -or $normal[0].partitions.Count -ne 1 -or $normal[1].partitions.Count -ne 0 -or $normal[1].partitionReadError) { throw 'Empty disk blocked inventory' }
$global:OxpInventoryTestScenario='missing'
$missing=(& $reader) | ConvertFrom-Json
if (-not $missing[0].partitionReadError) { throw 'Incomplete inventory was accepted' }
$global:OxpInventoryTestScenario='error'
$rejected=$false
try { & $reader | Out-Null } catch { $rejected=$true }
if (-not $rejected) { throw 'Partition query failure was swallowed' }
'PASS: empty disk, healthy disk, incomplete snapshot, query failure; no physical disk access.'
