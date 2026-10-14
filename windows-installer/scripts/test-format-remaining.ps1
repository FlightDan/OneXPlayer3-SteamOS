# Storage commands are mocked in memory. Never writes a real disk.
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path (Split-Path $PSScriptRoot -Parent) ('work/format-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$requestPath = Join-Path $testRoot 'format-request.json'
$global:ntfsTestProof = @()
function Reset-Fixture {
    $global:ntfsTestDisk = [pscustomobject]@{ Number=42; Guid='11111111-1111-1111-1111-111111111111'; SerialNumber='fixture'; LogicalSectorSize=512; FriendlyName='Mock'; Size=256GB; PartitionStyle='GPT'; BusType='NVMe'; IsBoot=$false; IsSystem=$false; IsOffline=$false; IsReadOnly=$false }
    $global:ntfsTestParts = @([pscustomobject]@{ DiskNumber=42; PartitionNumber=1; Guid='22222222-2222-2222-2222-222222222222'; Offset=1MB; Size=260MB; Type='System'; GptType='C12A7328-F81F-11D2-BA4B-00A0C93EC93B'; DriveLetter=''; IsBoot=$false; IsSystem=$true; IsHidden=$false; IsReadOnly=$false; IsOffline=$false; AccessPaths=@() })
    $global:ntfsTestCreates=0; $global:ntfsTestFormats=0; $global:ntfsTestWrongCreated=$false; $global:ntfsTestExistingChanged=$false
}
function Get-Disk { param($Number) $global:ntfsTestDisk }
function Get-Partition { param($DiskNumber,$PartitionNumber) if ($PSBoundParameters.ContainsKey('PartitionNumber')) { $global:ntfsTestParts | Where-Object PartitionNumber -eq $PartitionNumber } else { $global:ntfsTestParts } }
function Get-Volume { param([Parameter(ValueFromPipeline=$true)]$InputObject) process { $null } }
function Get-CimInstance { param($ClassName) if ($ClassName -ne 'Win32_PageFileUsage') { throw 'Unexpected CIM class' } }
function Get-ItemProperty { param($LiteralPath) [pscustomobject]@{} }
function New-Partition {
    param($DiskNumber,$Offset,$Size,$Alignment,$GptType)
    if ($DiskNumber -ne 42 -or $Offset -ne 261MB+100GB -or $Size -ne 256GB-1MB-(261MB+100GB) -or $Alignment -ne 1MB) { throw 'Unexpected creation target' }
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
    [pscustomobject]@{ FileSystemType='NTFS'; AllocationUnitSize=4096; HealthStatus='Healthy' }
}
function Add-PartitionAccessPath { param([Parameter(ValueFromPipeline=$true)]$InputObject,[switch]$AssignDriveLetter) process { if ($InputObject.Guid -ne '33333333-3333-3333-3333-333333333333') { throw 'Wrong letter target' }; $InputObject.DriveLetter='Z' } }
function Save-Request {
    $snapshot = & (Join-Path $PSScriptRoot 'read-disks.ps1')
    @{ Selection=@{Snapshot=$snapshot;Example=$false;Disk=42;Start=261MB;Capacity=100GB};Language='en-US' } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $requestPath
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
Require ((Get-Content (Join-Path $testRoot 'format-result.json') -Raw | ConvertFrom-Json).phase -eq 'verified') 'verified-journal'
Reject-Change { $global:ntfsTestDisk.Guid='99999999-9999-9999-9999-999999999999' } 'disk-swap-blocked'
Reject-Change { $global:ntfsTestDisk.SerialNumber='changed' } 'serial-change-blocked'
Reject-Change { $global:ntfsTestDisk.IsReadOnly=$true } 'readonly-blocked'
Reject-Change { $global:ntfsTestParts[0].Size += 1MB } 'layout-change-blocked'
Reject-Change { $global:ntfsTestWrongCreated=$true } 'wrong-created-range-never-formatted' 1
Reject-Change { $global:ntfsTestExistingChanged=$true } 'changed-existing-partition-never-formatted' 1
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
