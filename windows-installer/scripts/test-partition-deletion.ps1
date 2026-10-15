# In-memory Storage/CIM mocks only. This test never calls a physical disk cmdlet.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$testDir = Join-Path $taskRoot ('work/delete-policy-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDir | Out-Null
$requestPath = Join-Path $testDir 'delete-request.json'
$global:partitionDeletionTest_deletes = 0
$global:partitionDeletionTest_proof = @()
$global:partitionDeletionTest_volumeRoot = '\\?\Volume{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}\'
function Reset-Fixture {
    $global:partitionDeletionTest_disk = [pscustomobject]@{ Number=42; Guid='11111111-1111-1111-1111-111111111111'; SerialNumber='fixture-only'; LogicalSectorSize=512; FriendlyName='Mock data disk'; Size=512GB; PartitionStyle='GPT'; BusType='NVMe'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false }
    $global:partitionDeletionTest_parts = @(
        [pscustomobject]@{ PartitionNumber=1; Guid='22222222-2222-2222-2222-222222222222'; Offset=1MB; Size=260MB; Type='System'; GptType='C12A7328-F81F-11D2-BA4B-00A0C93EC93B'; DriveLetter=''; IsBoot=$false; IsSystem=$true; IsHidden=$false; IsReadOnly=$false; IsOffline=$false; AccessPaths=@() },
        [pscustomobject]@{ PartitionNumber=2; Guid='33333333-3333-3333-3333-333333333333'; Offset=261MB; Size=100GB; Type='Basic'; GptType='EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'; DriveLetter='Z'; IsBoot=$false; IsSystem=$false; IsHidden=$false; IsReadOnly=$false; IsOffline=$false; AccessPaths=@('Z:\',$global:partitionDeletionTest_volumeRoot) })
    foreach ($part in $global:partitionDeletionTest_parts) { $part | Add-Member NoteProperty DiskNumber 42 }
    $global:partitionDeletionTest_volume = [pscustomobject]@{ Path=$global:partitionDeletionTest_volumeRoot; FileSystemType='NTFS'; FileSystemLabel='Disposable fixture'; SizeRemaining=50GB; HealthStatus='Healthy' }
    $global:partitionDeletionTest_otherDisks = @()
    $global:partitionDeletionTest_pagefile = 'C:\pagefile.sys'; $global:partitionDeletionTest_windowsFiles = $false; $global:partitionDeletionTest_deletes = 0
}
function Get-Disk {
    param($Number)
    $disks = @($global:partitionDeletionTest_otherDisks) + @($global:partitionDeletionTest_disk)
    if ($PSBoundParameters.ContainsKey('Number')) { $disks | Where-Object Number -eq $Number } else { $disks }
}
function Get-Partition {
    param($DiskNumber, $PartitionNumber)
    $parts = $global:partitionDeletionTest_parts
    if ($PSBoundParameters.ContainsKey('DiskNumber')) { $parts = @($parts | Where-Object DiskNumber -eq $DiskNumber) }
    if ($PSBoundParameters.ContainsKey('PartitionNumber')) { $parts | Where-Object PartitionNumber -eq $PartitionNumber } else { $parts }
}
function Get-Volume { param([Parameter(ValueFromPipeline=$true)]$InputObject) process { $global:partitionDeletionTest_volume } }
function Get-CimInstance { param($ClassName) if ($ClassName -ne 'Win32_PageFileUsage') { throw 'Unexpected CIM query' }; [pscustomobject]@{ Name=$global:partitionDeletionTest_pagefile } }
function Get-ItemProperty { param($LiteralPath) [pscustomobject]@{ DumpFile='C:\Windows\MEMORY.DMP' } }
function Test-Path { param($LiteralPath,$PathType) if ($LiteralPath -eq $global:partitionDeletionTest_volumeRoot) { return $true }; return $global:partitionDeletionTest_windowsFiles }
function Remove-Partition {
    param([Parameter(ValueFromPipeline=$true)]$InputObject, [switch]$Confirm)
    process {
        if ($InputObject.Guid -ne '33333333-3333-3333-3333-333333333333') { throw 'Test attempted to delete an unexpected partition.' }
        $global:partitionDeletionTest_deletes++
        $global:partitionDeletionTest_parts = @($global:partitionDeletionTest_parts | Where-Object Guid -ne $InputObject.Guid)
    }
}
function Save-Request {
    $snapshot = & (Join-Path $PSScriptRoot 'read-disks.ps1')
    @{ Snapshot=$snapshot; Example=$false; Disk=$global:partitionDeletionTest_disk.Number; Start=261MB; Language='en-US' } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $requestPath -Encoding UTF8
}
function Set-MultiDiskFixture([int]$Number) {
    $global:partitionDeletionTest_disk.Number = $Number
    foreach ($part in $global:partitionDeletionTest_parts) { $part.DiskNumber = $Number }
    $global:partitionDeletionTest_otherDisks = @([pscustomobject]@{ Number=99; Guid='99999999-9999-9999-9999-999999999999'; SerialNumber='unrelated-fixture'; LogicalSectorSize=512; FriendlyName='Other mock disk'; Size=80GB; PartitionStyle='GPT'; BusType='SATA'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false })
}
function Require($Condition, [string]$Name) { if (-not $Condition) { throw "Failed: $Name" }; $global:partitionDeletionTest_proof += $Name }
function Reject-Change([scriptblock]$Change, [string]$Name) {
    Reset-Fixture; Save-Request; & $Change
    $rejected = $false
    try { & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath } catch { $rejected = $true }
    Require ($rejected -and $global:partitionDeletionTest_deletes -eq 0) $Name
}
Reset-Fixture; Save-Request
& (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath -ValidateOnly
Require ($global:partitionDeletionTest_deletes -eq 0) 'pre-confirmation-validation-never-deletes'
& (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath
Require ($global:partitionDeletionTest_deletes -eq 1 -and $global:partitionDeletionTest_parts.Count -eq 1 -and $global:partitionDeletionTest_parts[0].PartitionNumber -eq 1) 'deletes-exactly-reviewed-data-partition-and-keeps-efi'
foreach ($number in @(0,1,42)) {
    Reset-Fixture; Set-MultiDiskFixture $number; Save-Request
    & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath -ValidateOnly
    Require ($global:partitionDeletionTest_deletes -eq 0) "multi-disk-$number-validation-never-deletes"
    & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath
    Require ($global:partitionDeletionTest_deletes -eq 1 -and $global:partitionDeletionTest_parts.Count -eq 1 -and $global:partitionDeletionTest_parts[0].IsSystem) "multi-disk-$number-deletes-only-reviewed-partition"
}
foreach ($stage in @('reviewed','fresh')) {
    foreach ($kind in @('missing','duplicate')) {
        Reset-Fixture; Set-MultiDiskFixture 0
        if ($stage -eq 'fresh') { Save-Request }
        if ($kind -eq 'missing') { $global:partitionDeletionTest_disk.Number = 98 }
        else { $global:partitionDeletionTest_otherDisks[0].Number = 0 }
        if ($stage -eq 'reviewed') {
            Save-Request
            # Keep the requested disk fixed even when it is absent from the snapshot.
            $request = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
            $request.Disk = 0
            $request | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $requestPath -Encoding UTF8
        }
        $message = ''
        try { & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath } catch { $message = $_.Exception.Message }
        $expectedMessage = if ($stage -eq 'reviewed') { 'Ambiguous reviewed disk.' } else { 'Disk is missing; refresh the disk list.' }
        Require ($message -eq $expectedMessage -and $global:partitionDeletionTest_deletes -eq 0) "reject-$stage-$kind-disk-before-delete"
    }
}
Reject-Change { $global:partitionDeletionTest_disk.Guid = '99999999-9999-9999-9999-999999999999' } 'reject-disk-swap'
Reject-Change { $global:partitionDeletionTest_disk.SerialNumber = 'different' } 'reject-serial-change'
Reject-Change { $global:partitionDeletionTest_disk.IsReadOnly = $true } 'reject-readonly-disk'
Reject-Change { $global:partitionDeletionTest_disk.IsOffline = $true } 'reject-offline-disk'
Reject-Change { $global:partitionDeletionTest_disk.PartitionStyle = 'MBR' } 'reject-mbr'
Reject-Change { $global:partitionDeletionTest_disk.BusType = 'Spaces' } 'reject-storage-spaces'
Reject-Change { $global:partitionDeletionTest_parts[1].Guid = '99999999-9999-9999-9999-999999999999' } 'reject-partition-swap'
Reject-Change { $global:partitionDeletionTest_parts[1].Offset += 1MB } 'reject-moved-partition'
Reject-Change { $global:partitionDeletionTest_parts[1].Size -= 1MB } 'reject-resized-partition'
Reject-Change { $global:partitionDeletionTest_parts[0].Size -= 1MB } 'reject-other-partition-layout-change'
Reject-Change { $global:partitionDeletionTest_parts[1].IsBoot = $true } 'reject-boot-partition'
Reject-Change { $global:partitionDeletionTest_parts[1].IsSystem = $true } 'reject-system-partition'
Reject-Change { $global:partitionDeletionTest_parts[1].IsHidden = $true } 'reject-hidden-partition'
Reject-Change { $global:partitionDeletionTest_parts[1].IsReadOnly = $true } 'reject-readonly-partition'
Reject-Change { $global:partitionDeletionTest_parts[1].PSObject.Properties.Remove('IsSystem') } 'reject-missing-protection-metadata'
Reject-Change { $global:partitionDeletionTest_parts[1].GptType = 'DE94BBA4-06D1-4D40-A16A-BFD50179D6AC' } 'reject-recovery-type'
Reject-Change { $global:partitionDeletionTest_volume.FileSystemType = 'Unknown' } 'reject-locked-or-unknown-filesystem'
foreach ($unknownType in @('0FC63DAF-8483-4772-8E79-3D69D8477DE4','99999999-9999-9999-9999-999999999999')) {
    Reset-Fixture
    $global:partitionDeletionTest_parts[1].GptType = $unknownType
    $global:partitionDeletionTest_parts[1].Type = 'Unknown'
    $global:partitionDeletionTest_parts[1].AccessPaths = @()
    $global:partitionDeletionTest_parts[1].DriveLetter = ''
    $global:partitionDeletionTest_volume = $null
    Save-Request
    & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath
    Require ($global:partitionDeletionTest_deletes -eq 1 -and $global:partitionDeletionTest_parts.Count -eq 1) "delete-unrecognized-filesystem-$unknownType-preserves-efi"
}
Reset-Fixture
$global:partitionDeletionTest_volume.FileSystemType = 'Unknown'
$global:partitionDeletionTest_pagefile = 'Z:\pagefile.sys'
Save-Request
$unknownBlocked = $false
try { & (Join-Path $PSScriptRoot 'delete-partition.ps1') -RequestPath $requestPath } catch { $unknownBlocked = $true }
Require ($unknownBlocked -and $global:partitionDeletionTest_deletes -eq 0) 'unknown-filesystem-still-protects-pagefile'
Reject-Change { $global:partitionDeletionTest_volume.HealthStatus = 'Warning' } 'reject-unhealthy-volume'
Reject-Change { $global:partitionDeletionTest_pagefile = 'Z:\pagefile.sys' } 'reject-pagefile-volume'
Reject-Change { $global:partitionDeletionTest_windowsFiles = $true } 'reject-windows-or-boot-files'
Reject-Change { $global:partitionDeletionTest_parts[1].AccessPaths = @((Split-Path $PSScriptRoot -Parent) + '\') } 'reject-installer-volume'
Reject-Change { $r = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json; $r.Example=$true; $r | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $requestPath -Encoding UTF8 } 'reject-example-at-write-boundary'
@{ passed=$true; proof=$global:partitionDeletionTest_proof; scope='In-memory mocks; no physical disk writes or VHD operations.' } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $testDir 'checks.json') -Encoding UTF8
Write-Output "Passed $($global:partitionDeletionTest_proof.Count) deletion checks: $testDir"
