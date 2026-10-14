param([Parameter(Mandatory=$true)][string]$BatPath)
$ErrorActionPreference = 'Stop'
$content = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $BatPath))
$body = [regex]::Split($content, '(?m)^# OXP3-POWERSHELL\r?$')[1]
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($body, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Execute only the dependency-injected transaction function, never the entry point.
$function = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-SteamOSRestart' }, $true)
. ([scriptblock]::Create($function.Extent.Text))
# Compile the exact native wrapper but do not call any of its methods.
$native = $ast.Find({ param($node) $node -is [Management.Automation.Language.StringConstantExpressionAst] -and $node.Value.Contains('public static class OxpDesktopFirmware') }, $true)
Add-Type -TypeDefinition $native.Value
$script:checks = @()
function Require($value, $label) { if (!$value) { throw $label }; $script:checks += $label }
function Variable([byte[]]$bytes, [uint32]$attributes = 7) { [pscustomobject]@{ Data = $bytes; Attributes = $attributes } }
function Reset {
    $script:store = @{ Boot60AB = (Variable ([byte[]]@(1,0,0,0,4,0,0,0))) }
    $script:writes = @(); $script:restarts = @(); $script:mode = ''; $script:reads = 0
}
$read = {
    param($key)
    if ($key -eq 'BootNext') {
        $script:reads++
        if ($script:mode -eq 'concurrent-before' -and $script:reads -eq 2) { $script:store.BootNext = Variable ([byte[]]@(3,0)) }
        if ($script:mode -eq 'bad-readback' -and $script:reads -eq 3) { $script:store.BootNext = Variable ([byte[]]@(9,0)) }
    }
    $script:store[$key]
}
$write = {
    param($key, $value)
    if ($key -ne 'BootNext') { throw 'unexpected write' }
    $script:writes += $key
    if ($script:mode -eq 'write-denied') { throw 'write denied' }
    if ($script:mode -eq 'rollback-denied' -and $script:writes.Count -eq 2) { throw 'restore denied' }
    $script:store[$key] = $value
}
$confirm = { param($external) $true }
$restart = {
    param($external)
    $script:restarts += $external
    if ($script:mode -eq 'concurrent-after') { $script:store.BootNext = Variable ([byte[]]@(8,0)); throw 'shutdown failed' }
    if ($script:mode -in @('shutdown-failed', 'rollback-denied')) { throw 'shutdown failed' }
}
$expected = [Convert]::ToBase64String([byte[]]@(1,0,0,0,4,0,0,0))
function Run([string]$name = 'Boot60AB', [scriptblock]$confirmation = $confirm) {
    Invoke-SteamOSRestart $name $expected $read $write $confirmation $restart
}
function Fails([scriptblock]$action, [string]$message) {
    $failure = $null
    try { & $action } catch { $failure = $_.ToString() }
    Require ($null -ne $failure -and $failure.Contains($message)) ('reject-' + $message)
}
Reset; Run
Require ($script:restarts.Count -eq 1 -and !$script:restarts[0] -and [BitConverter]::ToUInt16($script:store.BootNext.Data,0) -eq 0x60AB) 'one-time-target-and-normal-restart'
Reset; Run -confirmation { $false }
Require ($script:writes.Count -eq 0 -and $script:restarts.Count -eq 0) 'cancel-has-no-effects'
Reset; $script:store.Remove('Boot60AB'); Fails { Run } 'missing or changed'
Require ($script:writes.Count -eq 0 -and $script:restarts.Count -eq 0) 'missing-entry-never-restarts'
Reset; $script:store.Boot60AB = Variable ([byte[]]@(2,0)); Fails { Run } 'missing or changed'
Reset; Fails { Run -confirmation { $script:store.Boot60AB = $null; $true } } 'changed before restart'
Reset; $script:mode = 'concurrent-before'; Fails { Run } 'BootNext changed'
Require ($script:writes.Count -eq 0 -and $script:restarts.Count -eq 0) 'concurrent-bootnext-preserved'
Reset; $script:mode = 'write-denied'; Fails { Run } 'write denied'
Require ($script:restarts.Count -eq 0) 'write-failure-never-restarts'
Reset; $script:mode = 'bad-readback'; Fails { Run } 'readback differs'
Require ($script:restarts.Count -eq 0 -and $script:store.BootNext.Data[0] -eq 9) 'readback-failure-preserves-concurrent-value'
foreach ($existing in @($false, $true)) {
    Reset; $script:mode = 'shutdown-failed'
    if ($existing) { $script:store.BootNext = Variable ([byte[]]@(4,0)) 3 }
    Fails { Run } 'shutdown failed'
    Require (($existing -and $script:store.BootNext.Data[0] -eq 4 -and $script:store.BootNext.Attributes -eq 3) -or (!$existing -and $null -eq $script:store.BootNext)) ('rollback-original-' + $existing)
}
Reset; $script:mode = 'concurrent-after'; Fails { Run } 'shutdown failed'
Require ($script:writes.Count -eq 1 -and $script:store.BootNext.Data[0] -eq 8) 'rollback-preserves-other-writer'
Reset; $script:mode = 'rollback-denied'; Fails { Run } 'restoration failed'
Reset; Run -name ''
Require ($script:writes.Count -eq 0 -and $script:restarts.Count -eq 1 -and $script:restarts[0]) 'external-firmware-menu-without-nvram'
Reset; Run -name '' -confirmation { $false }
Require ($script:writes.Count -eq 0 -and $script:restarts.Count -eq 0) 'external-cancel'
# Exercise the real CMD/PowerShell bootstrap in a path containing metacharacters.
# Replace the entire production PowerShell body with a harmless proof write.
$testDirectory = Join-Path (Join-Path (Split-Path $PSScriptRoot -Parent) 'work') ('desktop-bootstrap-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testDirectory
$unicodeName = -join ([char[]]@(0x4E2D, 0x6587))
$testDirectory = Join-Path $testDirectory ($unicodeName + " desktop & 'quoted' % !")
$null = New-Item -ItemType Directory -Path $testDirectory
$testBat = Join-Path $testDirectory ($unicodeName + ' SteamOS.bat')
$proof = Join-Path $testDirectory 'proof.txt'
$header = [regex]::Split($content, '(?m)^# OXP3-POWERSHELL\r?$')[0]
$safe = $header + "# OXP3-POWERSHELL`r`n[IO.File]::WriteAllText(`$env:OXP3_BOOTSTRAP_PROOF, 'passed')`r`n"
[IO.File]::WriteAllText($testBat, $safe, (New-Object Text.UTF8Encoding($false)))
$env:OXP3_BOOTSTRAP_PROOF = $proof
try {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = "$env:SystemRoot\System32\cmd.exe"
    $start.Arguments = '/d /v:off /c ""' + $testBat + '""'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    Require ($process.ExitCode -eq 0 -and [IO.File]::ReadAllText($proof) -eq 'passed') 'real-bat-bootstrap-unicode-metacharacters'
    # Build the production UAC command, then run its payload as an ordinary child.
    # This checks quoting and Unicode without requesting elevation.
    $previousBat = $env:OXP3_STEAMOS_BAT
    try {
        $env:OXP3_STEAMOS_BAT = $testBat
        foreach ($variableName in @('path64', 'command', 'encoded')) {
            $assignment = $ast.Find({ param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq $variableName }, $true)
            . ([scriptblock]::Create($assignment.Extent.Text))
        }
        [IO.File]::WriteAllText($proof, 'pending')
        $start.FileName = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $start.Arguments = '-NoProfile -EncodedCommand ' + $encoded
        $process = [Diagnostics.Process]::Start($start)
        $process.WaitForExit()
        Require ($process.ExitCode -eq 0 -and [IO.File]::ReadAllText($proof) -eq 'passed') 'uac-payload-path-encoding-without-elevation'
    } finally { $env:OXP3_STEAMOS_BAT = $previousBat }
} finally { Remove-Item Env:OXP3_BOOTSTRAP_PROOF }
[pscustomobject]@{ checks = $script:checks; count = $script:checks.Count; nativeCompiled = $true; firmwareWritten = $false; restartExecuted = $false } | ConvertTo-Json -Depth 4
