$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'linux-storage-probe.ps1')
Initialize-LinuxStorageProbe
# The native reader is never called: identification and eligibility use in-memory fixtures.
function Put-U16([byte[]]$Bytes, [int]$At, [uint16]$Value) { [BitConverter]::GetBytes($Value).CopyTo($Bytes,$At) }
function Put-U32([byte[]]$Bytes, [int]$At, [uint32]$Value) { [BitConverter]::GetBytes($Value).CopyTo($Bytes,$At) }
function Put-U64([byte[]]$Bytes, [int]$At, [uint64]$Value) { [BitConverter]::GetBytes($Value).CopyTo($Bytes,$At) }
function Require([bool]$Condition, [string]$Name) { if (-not $Condition) { throw $Name } }
$ext = New-Object byte[] 131072
$e = 1024
Put-U32 $ext $e 4096; Put-U32 $ext ($e+4) 32768; Put-U32 $ext ($e+0x18) 2
Put-U32 $ext ($e+0x20) 32768; Put-U32 $ext ($e+0x28) 4096
Put-U16 $ext ($e+0x38) 0xef53; Put-U32 $ext ($e+0x4c) 1; Put-U32 $ext ($e+0x60) 0x40
([guid]'12345678-1234-4321-8765-123456789abc').ToByteArray().CopyTo($ext,$e+0x68)
Require ([OxpLinuxStorageProbe]::Identify($ext,128MB) -eq 'ext4') 'ext4 superblock fixture not identified'
Require ([OxpLinuxStorageProbe]::Identify($ext,64MB) -eq '') 'filesystem larger than partition accepted'
Put-U32 $ext ($e+0x60) 0
Require ([OxpLinuxStorageProbe]::Identify($ext,128MB) -eq '') 'ext2/ext3 guessed as ext4'
Put-U32 $ext ($e+0x60) 0x40
$btrfs = New-Object byte[] 131072
$b = 65536
([guid]'12345678-1234-4321-8765-123456789abc').ToByteArray().CopyTo($btrfs,$b+0x20)
[Text.Encoding]::ASCII.GetBytes('_BHRfS_M').CopyTo($btrfs,$b+0x40)
Put-U64 $btrfs ($b+0x30) 65536; Put-U64 $btrfs ($b+0x48) 1
Put-U64 $btrfs ($b+0x50) 1048576; Put-U64 $btrfs ($b+0x58) 2097152
Put-U64 $btrfs ($b+0x70) 128MB; Put-U64 $btrfs ($b+0x78) 1MB; Put-U64 $btrfs ($b+0x88) 1
Put-U32 $btrfs ($b+0x90) 4096; Put-U32 $btrfs ($b+0x94) 16384
Require ([OxpLinuxStorageProbe]::Identify($btrfs,128MB) -eq 'btrfs') 'Btrfs primary superblock fixture not identified'
Put-U64 $btrfs ($b+0x88) 2
Require ([OxpLinuxStorageProbe]::Identify($btrfs,128MB) -eq '') 'multi-device Btrfs accepted'
Put-U64 $btrfs ($b+0x88) 1
Put-U64 $btrfs ($b+0x30) 67108864
Require ([OxpLinuxStorageProbe]::Identify($btrfs,128MB) -eq '') 'Btrfs mirror at primary location accepted'
Put-U64 $btrfs ($b+0x30) 65536
$ambiguous = [byte[]]$ext.Clone(); [Array]::Copy($btrfs,65536,$ambiguous,65536,4096)
Require ([OxpLinuxStorageProbe]::Identify($ambiguous,128MB) -eq '') 'conflicting signatures accepted'
$encrypted = [byte[]]$ext.Clone(); [Text.Encoding]::ASCII.GetBytes('LUKS').CopyTo($encrypted,0); $encrypted[4]=0xba; $encrypted[5]=0xbe
Require ([OxpLinuxStorageProbe]::Identify($encrypted,128MB) -eq '') 'LUKS stale ext4 accepted'
$encrypted = [byte[]]$ext.Clone(); [Text.Encoding]::ASCII.GetBytes('-FVE-FS-').CopyTo($encrypted,3)
Require ([OxpLinuxStorageProbe]::Identify($encrypted,128MB) -eq '') 'BitLocker stale ext4 accepted'
Require ([OxpLinuxStorageProbe]::Identify((New-Object byte[] 131072),128MB) -eq '') 'unknown guessed as Linux filesystem'
Require ([OxpLinuxStorageProbe]::Identify((New-Object byte[] 1024),128MB) -eq '') 'truncated signature accepted'
$layout = New-Object byte[] 336
$diskId = [guid]'12345678-1234-4321-8765-123456789abc'
$partId = [guid]'abcdefab-1234-4321-8765-123456789abc'
$linuxType = [guid]'0FC63DAF-8483-4772-8E79-3D69D8477DE4'
Put-U32 $layout 0 1; Put-U32 $layout 4 1; $diskId.ToByteArray().CopyTo($layout,8)
Put-U32 $layout 48 1; Put-U64 $layout 56 1MB; Put-U64 $layout 64 128MB
$linuxType.ToByteArray().CopyTo($layout,80); $partId.ToByteArray().CopyTo($layout,96)
Require ([OxpLinuxStorageProbe]::MatchesLayout($layout,192,$diskId,$partId,$linuxType,1MB,128MB)) 'matching GPT fixture rejected'
Require (-not [OxpLinuxStorageProbe]::MatchesLayout($layout,192,$partId,$partId,$linuxType,1MB,128MB)) 'replacement disk accepted'
Require (-not [OxpLinuxStorageProbe]::MatchesLayout($layout,192,$diskId,$partId,$linuxType,2MB,128MB)) 'changed partition offset accepted'
Require (-not [OxpLinuxStorageProbe]::MatchesLayout($layout,191,$diskId,$partId,$linuxType,1MB,128MB)) 'truncated GPT accepted'
$layout[77]=1
Require (-not [OxpLinuxStorageProbe]::MatchesLayout($layout,192,$diskId,$partId,$linuxType,1MB,128MB)) 'service partition accepted'
$layout[77]=0
foreach ($flag in @([uint64]1,[uint64]0x1000000000000000,[uint64]0x4000000000000000,[uint64]::Parse('9223372036854775808'))) {
    Put-U64 $layout 112 $flag
    Require (-not [OxpLinuxStorageProbe]::MatchesLayout($layout,192,$diskId,$partId,$linuxType,1MB,128MB)) 'protected GPT attributes accepted'
}
Put-U64 $layout 112 0; Put-U32 $layout 4 2; [Array]::Copy($layout,48,$layout,192,144)
Require (-not [OxpLinuxStorageProbe]::MatchesLayout($layout,336,$diskId,$partId,$linuxType,1MB,128MB)) 'duplicate partition GUID accepted'
$probeDisk = [pscustomobject]@{ PartitionStyle='GPT'; BusType='SCSI'; IsOffline=$false; IsReadOnly=$false }
$probePart = [pscustomobject]@{ GptType='0FC63DAF-8483-4772-8E79-3D69D8477DE4'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsHidden=$true; IsReadOnly=$null }
Require (Test-LinuxStorageProbeEligible $probeDisk $probePart $null) 'Linux data on SCSI card reader excluded before native verification'
$probePart.IsSystem=$true
Require (-not (Test-LinuxStorageProbeEligible $probeDisk $probePart $null)) 'system partition eligible for signature read'
$probePart.IsSystem=$false; $probePart.IsReadOnly=$true
Require (-not (Test-LinuxStorageProbeEligible $probeDisk $probePart $null)) 'read-only partition eligible for signature read'
$probePart.IsReadOnly=$null; $probePart.GptType='4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709'
Require (-not (Test-LinuxStorageProbeEligible $probeDisk $probePart $null)) 'Linux root GPT type eligible for signature read'
$probePart.GptType='EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'
Require (-not (Test-LinuxStorageProbeEligible $probeDisk $probePart $null)) 'hidden Microsoft data partition eligible for signature read'
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
    $partition = [pscustomobject]@{ DiskNumber=0; PartitionNumber=1; Guid=[guid]::NewGuid().ToString(); Offset=1MB; Size=128GB;
        Type='Basic'; GptType='{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}'; DriveLetter='';
        IsBoot=$false; IsSystem=$false; IsHidden=$false }
    if ($global:OxpInventoryTestScenario -in @('linux','probe-error')) {
        $partition.GptType='0FC63DAF-8483-4772-8E79-3D69D8477DE4'; $partition.IsHidden=$true
        $partition | Add-Member NoteProperty IsOffline $false
        $partition | Add-Member NoteProperty IsReadOnly $null
    }
    $partition
}
function Get-Volume { [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$Partition) process { } }
$reader=Join-Path $PSScriptRoot 'read-disks.ps1'
# Run the production inventory body with a mocked native filesystem reader.
# Removing its helper imports prevents them from overwriting the mocks.
# Disk/partition/volume cmdlets above are mocked too; native disk access cannot run.
$readerSource = (Get-Content -LiteralPath $reader -Raw).Replace(". (Join-Path `$PSScriptRoot 'linux-storage-probe.ps1')", '')
$readerSource = $readerSource.Replace(". (Join-Path `$PSScriptRoot 'partition-delete-policy.ps1')", '')
$readerSource = $readerSource.Replace('$PSScriptRoot', ("'" + $PSScriptRoot.Replace("'", "''") + "'"))
function Get-PartitionDeletionBlockReason($Disk, $Partition, $Volume) { return 'Deletion policy fixture; no native access.' }
function Get-LinuxStorageFilesystem($Disk, $Partition) {
    if ($global:OxpInventoryTestScenario -eq 'linux') { return 'ext4' }
    throw 'Native filesystem reader fixture failure'
}
function Invoke-InventoryFixture { & ([scriptblock]::Create($readerSource)) }
$normal = (Invoke-InventoryFixture) | ConvertFrom-Json
if ($normal.Count -ne 2 -or $normal[0].partitions.Count -ne 1 -or $normal[1].partitions.Count -ne 0 -or $normal[1].partitionReadError) { throw 'Empty disk blocked inventory' }
$global:OxpInventoryTestScenario='linux'
$linux=(Invoke-InventoryFixture) | ConvertFrom-Json
Require ($linux[0].partitions[0].filesystem -eq 'ext4' -and $linux[0].partitions[0].filesystemSource -eq 'signature' -and $linux[0].partitions[0].sharedStorageSafe) 'Linux signature evidence missing from inventory'
$global:OxpInventoryTestScenario='probe-error'
$probeError=(Invoke-InventoryFixture) | ConvertFrom-Json
Require ($probeError.Count -eq 2 -and $probeError[0].partitions[0].filesystemProbeError -and -not $probeError[0].partitions[0].sharedStorageSafe) 'signature read failure blocked disks or produced eligible filesystem'
$global:OxpInventoryTestScenario='missing'
$missing=(Invoke-InventoryFixture) | ConvertFrom-Json
if (-not $missing[0].partitionReadError) { throw 'Incomplete inventory was accepted' }
$global:OxpInventoryTestScenario='error'
$rejected=$false
try { Invoke-InventoryFixture | Out-Null } catch { $rejected=$true }
if (-not $rejected) { throw 'Partition query failure was swallowed' }
'PASS: ext4/Btrfs byte fixtures, encrypted/ambiguous/unknown and protected partitions, SCSI card reader eligibility, empty disk, healthy disk, incomplete snapshot, query failure; no physical disk access.'
