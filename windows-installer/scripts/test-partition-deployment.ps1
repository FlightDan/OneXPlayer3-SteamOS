param([ValidateSet('compact','internal','external')][string]$Mode='compact',[string]$Fixture,[string]$PreparedImage)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$env:DOTNET_CLI_HOME=Join-Path $taskRoot 'work/dotnet-home'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
if($Fixture -and $PreparedImage){throw 'Choose fixture export or a previously prepared image'}
$taskArguments=@((Join-Path $taskRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll'),'--cli')
if ($Mode -eq 'compact') {
    if($PreparedImage -or $Fixture){throw 'Compact mode creates its own fixture'}
    $taskArguments += 'native-partition-checks'
}
elseif($PreparedImage){$taskArguments += @('native-partition-stage',$PreparedImage,$Mode)}
else {
    if (-not $Fixture) { $Fixture=Join-Path $taskRoot 'work/uefi-af659f7667214d60b9ca44e9394d51c3/windows-fixture.qcow2' }
    $taskArguments += @('native-partition-deploy',$Fixture,$Mode)
}
& (Join-Path $taskRoot 'runtime/dotnet/dotnet.exe') @taskArguments
$taskExit=$LASTEXITCODE
$taskLog=Get-Content -LiteralPath (Join-Path $taskRoot 'logs/native-cli-result.txt') -Raw -Encoding UTF8
$taskEvidence=Join-Path $taskRoot ('logs/partition-deployment-'+$Mode+'-'+(Get-Date -Format yyyyMMdd-HHmmss)+'.txt')
[IO.File]::WriteAllText($taskEvidence,$taskLog,[System.Text.UTF8Encoding]::new($false))
if ($taskExit -ne 0 -or $taskLog -notmatch 'NATIVE_CLI_RESULT=passed') { throw $taskLog }
$taskLog
'PARTITION_LOG='+$taskEvidence
