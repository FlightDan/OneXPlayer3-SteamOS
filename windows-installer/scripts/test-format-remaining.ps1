# Storage commands are mocked in memory. Never writes a real disk.
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path (Split-Path $PSScriptRoot -Parent) ('work/format-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$requestPath = Join-Path $testRoot 'format-request.json'
$global:ntfsTestProof = @()
function Reset-Fixture {
    $global:ntfsTestDisk = [pscustomobject]@{ Number=42; Guid='11111111-1111-1111-1111-111111111111'; SerialNumber='fixture'; LogicalSectorSize=512; FriendlyName='Mock'; Size=256GB; PartitionStyle='GPT'; BusType='NVMe'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false }
    $global:ntfsTestSecondDisk = [pscustomobject]@{ Number=99; Guid='99999999-9999-9999-9999-999999999999'; SerialNumber='unrelated-fixture'; LogicalSectorSize=512; FriendlyName='Other'; Size=80GB; PartitionStyle='GPT'; BusType='SATA'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false }
    $global:ntfsTestParts = @([pscustomobject]@{ DiskNumber=42; PartitionNumber=1; Guid='22222222-2222-2222-2222-222222222222'; Offset=1MB; Size=260MB; Type='System'; GptType='C12A7328-F81F-11D2-BA4B-00A0C93EC93B'; DriveLetter=''; IsBoot=$false; IsSystem=$true; IsHidden=$false; IsReadOnly=$false; IsOffline=$false; AccessPaths=@() })
    $global:ntfsTestCreates=0; $global:ntfsTestFormats=0; $global:ntfsTestWrongCreated=$false; $global:ntfsTestExistingChanged=$false; $global:ntfsTestFormatFailure=$false
    $global:ntfsTestAlignRight=$false; $global:ntfsTestGapEnd=256GB-1MB
}
function Get-Disk { param($Number) $global:ntfsTestDisk; $global:ntfsTestSecondDisk }
function Get-Partition { param($DiskNumber,$PartitionNumber) if ($PSBoundParameters.ContainsKey('PartitionNumber')) { $global:ntfsTestParts | Where-Object PartitionNumber -eq $PartitionNumber } else { $global:ntfsTestParts } }
function Get-Volume { param([Parameter(ValueFromPipeline=$true)]$InputObject) process { $null } }
function Get-CimInstance { param($ClassName) if ($ClassName -ne 'Win32_PageFileUsage') { throw 'Unexpected CIM class' } }
function Get-ItemProperty { param($LiteralPath) [pscustomobject]@{} }
function New-Partition {
    param($DiskNumber,$Offset,$Size,$Alignment,$GptType)
    $expectedOffset = 261MB+100GB
    if ($global:ntfsTestAlignRight) { $expectedOffset = 261MB }
    if ($DiskNumber -ne 42 -or $Offset -ne $expectedOffset -or $Size -ne $global:ntfsTestGapEnd-261MB-100GB -or $Alignment -ne 1MB) { throw 'Unexpected creation target' }
    $global:ntfsTestCreates++
    $p = [pscustomobject]@{ DiskNumber=42; PartitionNumber=2; Guid='33333333-3333-3333-3333-333333333333'; Offset=$Offset; Size=$Size; Type='Basic'; GptType=$GptType; DriveLetter=''; IsBoot=$false; IsSystem=$false; IsHidden=$false; IsReadOnly=$false; IsOffline=$false; AccessPaths=@() }
    if ($global:ntfsTestWrongCreated) { $p.Offset += 1MB }
    if ($global:ntfsTestExistingChanged) { $global:ntfsTestParts[0].Size -= 1MB }
    $global:ntfsTestParts += $p
    $p
}
function Format-Volume {
    param($Partition,$FileSystem,$AllocationUnitSize,$NewFileSystemLabel,[switch]$Confirm)
    if ($Partition.Guid -ne '33333333-3333-3333-3333-333333333333' -or $FileSystem -ne 'NTFS' -or $AllocationUnitSize -ne 4096) { throw 'Unexpected format target' }
    $global:ntfsTestFormats++
    if ($global:ntfsTestFormatFailure) { throw 'Fixture formatting failed after partition creation.' }
    [pscustomobject]@{ FileSystemType='NTFS'; AllocationUnitSize=4096; HealthStatus='Healthy' }
}
function Add-PartitionAccessPath { param([Parameter(ValueFromPipeline=$true)]$InputObject,[switch]$AssignDriveLetter) process { if ($InputObject.Guid -ne '33333333-3333-3333-3333-333333333333') { throw 'Wrong letter target' }; $InputObject.DriveLetter='Z' } }
function Save-Request {
    param([switch]$Right)
    $global:ntfsTestAlignRight = [bool]$Right
    $snapshot = & (Join-Path $PSScriptRoot 'read-disks.ps1')
    $choice = @{Snapshot=$snapshot;Example=$false;Disk=42;Start=261MB;Capacity=100GB}
    if ($Right) { $choice.AlignRight = $true }
    @{ Selection=$choice;Language='en-US' } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $requestPath
}
function Require($ok,$name) { if (-not $ok) { throw "Failed: $name" }; $global:ntfsTestProof += $name }
function Reject-Change([scriptblock]$Change,$name,$creates=0) {
    Reset-Fixture; Save-Request; & $Change
    $rejected=$false
    try { & (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath } catch { $rejected=$true }
    Require ($rejected -and $global:ntfsTestCreates -eq $creates -and $global:ntfsTestFormats -eq 0) $name
}
Reset-Fixture; Save-Request
& (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath -ValidateOnly
Require ($global:ntfsTestCreates -eq 0 -and $global:ntfsTestFormats -eq 0) 'validation-does-not-create-or-format'
& (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath
Require ($global:ntfsTestCreates -eq 1 -and $global:ntfsTestFormats -eq 1 -and $global:ntfsTestParts[0].Size -eq 260MB) 'exact-free-tail-ntfs-4k-existing-kept'
Require ($global:ntfsTestSecondDisk.Guid -eq '99999999-9999-9999-9999-999999999999') 'multiple-inventory-disks-bind-only-reviewed-target'
Require ((Get-Content (Join-Path $testRoot 'format-result.json') -Raw | ConvertFrom-Json).phase -eq 'verified') 'verified-journal'
Require ((Get-Content (Join-Path $testRoot 'format-result.json') -Raw | ConvertFrom-Json).alignRight -eq $false) 'legacy-missing-placement-defaults-left'
Reset-Fixture; Save-Request -Right
& (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath -ValidateOnly
Require ($global:ntfsTestCreates -eq 0 -and $global:ntfsTestFormats -eq 0) 'right-placement-validation-is-readonly'
& (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath
$rightResult = Get-Content (Join-Path $testRoot 'format-result.json') -Raw | ConvertFrom-Json
Require ($rightResult.phase -eq 'verified' -and $rightResult.alignRight -eq $true -and $rightResult.start -eq 261MB -and
    $rightResult.steamOSStart -eq 256GB-1MB-100GB -and $rightResult.steamOSSize -eq 100GB -and
    $rightResult.start+$rightResult.size -eq $rightResult.steamOSStart) 'right-steamos-left-ntfs-exact-ranges-and-journal'
Require ($global:ntfsTestCreates -eq 1 -and $global:ntfsTestFormats -eq 1 -and $global:ntfsTestParts[0].Size -eq 260MB) 'right-format-preserves-existing-partition'
Reset-Fixture
$global:ntfsTestParts += [pscustomobject]@{ DiskNumber=42; PartitionNumber=3; Guid='44444444-4444-4444-4444-444444444444'; Offset=200GB; Size=512MB; Type='Recovery'; GptType='DE94BBA4-06D1-4D40-A16A-BFD50179D6AC'; DriveLetter=''; IsBoot=$false; IsSystem=$false; IsHidden=$false; IsReadOnly=$false; IsOffline=$false; AccessPaths=@() }
$global:ntfsTestGapEnd=200GB
Save-Request -Right
& (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath
$boundedResult = Get-Content (Join-Path $testRoot 'format-result.json') -Raw | ConvertFrom-Json
Require ($boundedResult.start -eq 261MB -and $boundedResult.start+$boundedResult.size -eq 100GB -and $boundedResult.steamOSStart -eq 100GB -and
    $global:ntfsTestParts[1].Offset -eq 200GB -and $global:ntfsTestParts[1].Size -eq 512MB) 'right-bounded-gap-does-not-use-disk-tail-or-change-recovery'
Reset-Fixture; Save-Request; $global:ntfsTestFormatFailure=$true
$formatFailed=$false
try { & (Join-Path $PSScriptRoot 'format-remaining.ps1') -RequestPath $requestPath } catch { $formatFailed=$true }
Require ($formatFailed -and $global:ntfsTestCreates -eq 1 -and $global:ntfsTestFormats -eq 1 -and $global:ntfsTestParts.Count -eq 2 -and
    (Get-Content (Join-Path $testRoot 'format-result.json') -Raw | ConvertFrom-Json).phase -eq 'created') 'format-failure-keeps-created-partition-and-operation-record'
Reject-Change { $global:ntfsTestDisk.Guid='99999999-9999-9999-9999-999999999999' } 'disk-swap-blocked'
Reject-Change { $global:ntfsTestDisk.SerialNumber='changed' } 'serial-change-blocked'
Reject-Change { $global:ntfsTestDisk.IsReadOnly=$true } 'readonly-blocked'
Reject-Change { $global:ntfsTestParts[0].Size += 1MB } 'layout-change-blocked'
Reject-Change { $global:ntfsTestWrongCreated=$true } 'wrong-created-range-never-formatted' 1
Reject-Change { $global:ntfsTestExistingChanged=$true } 'changed-existing-partition-never-formatted' 1
foreach ($invalidPlacement in @('true',1,$null)) {
    Reject-Change {
        $r=Get-Content $requestPath -Raw|ConvertFrom-Json
        $r.Selection | Add-Member -NotePropertyName AlignRight -NotePropertyValue $invalidPlacement
        $r|ConvertTo-Json -Depth 12|Set-Content $requestPath
    } ('reject-placement-type-' + $(if ($null -eq $invalidPlacement) { 'null' } else { $invalidPlacement.GetType().Name }))
}
foreach ($mode in @('example','no-remainder','misaligned','existing-start','below-minimum')) {
    Reject-Change {
        $r=Get-Content $requestPath -Raw|ConvertFrom-Json
        switch ($mode) {
            'example' { $r.Selection.Example=$true }
            'no-remainder' { $r.Selection.Capacity=256GB-1MB-261MB }
            'misaligned' { $r.Selection.Capacity=100GB+512 }
            'existing-start' { $r.Selection.Start=1MB }
            'below-minimum' { $r.Selection.Capacity=63GB }
        }
        $r|ConvertTo-Json -Depth 12|Set-Content $requestPath
    } "reject-$mode"
}
@{passed=$true;proof=$global:ntfsTestProof;scope='In-memory storage mocks only.'}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $testRoot 'checks.json')
Write-Output "Passed $($global:ntfsTestProof.Count) format checks: $testRoot"
