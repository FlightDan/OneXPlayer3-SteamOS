param([Parameter(Mandatory)][string]$WorkingImage)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$WorkingImage = [IO.Path]::GetFullPath($WorkingImage)
$allowed = [IO.Path]::GetFullPath((Join-Path $projectRoot 'work')) + [IO.Path]::DirectorySeparatorChar
if (!$WorkingImage.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetExtension($WorkingImage) -ne '.img' -or
    !(Test-Path -LiteralPath ($WorkingImage + '.refind-test.json'))) { throw 'Expected an explicitly owned disposable rEFInd image' }
$owner = Get-Content -LiteralPath ($WorkingImage + '.refind-test.json') -Raw | ConvertFrom-Json
if ($owner.scope -ne 'disposable-refind-vm-only' -or $owner.image -ne $WorkingImage) { throw 'Image ownership mismatch' }
$directory = Split-Path $WorkingImage -Parent
$results = [Collections.Generic.List[object]]::new()
function Invoke-Check([string]$Name, [string[]]$Arguments) {
    $start = [Diagnostics.ProcessStartInfo]::new((Join-Path $projectRoot 'SteamOSInstaller.exe'))
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true; $start.WindowStyle = 'Hidden'
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($start); $process.WaitForExit()
    $code = $process.ExitCode; $process.Dispose()
    $record = Join-Path $directory ($Name + '.txt')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'logs/native-cli-result.txt') -Destination $record
    $results.Add([pscustomobject]@{name=$Name;passed=($code -eq 0);record=$record})
    $results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $directory 'acceptance.json') -Encoding utf8NoBOM
    Write-Output "$Name exit=$code"
    if ($code -ne 0) { Get-Content -LiteralPath $record -Tail 20; throw "Failed: $Name" }
}
function Invoke-Image([string]$Action) {
    $choice=Join-Path $directory ($Action+'.json')
    @{action=$Action} | ConvertTo-Json | Set-Content -LiteralPath $choice -Encoding utf8NoBOM
    Invoke-Check $Action @('--cli','refind-image',$WorkingImage,$choice)
}
Invoke-Image 'lifecycle'
Invoke-Check 'manual-steamos-boot' @('--cli','refind-boot',$WorkingImage,'manual')
Invoke-Image 'windows-probe'
Invoke-Check 'windows-efi-probe-boot' @('--cli','refind-boot',$WorkingImage,'windows-probe')
Invoke-Image 'uninstall'
Invoke-Check 'restored-steamos-boot' @('--cli','integration-boot',$WorkingImage)
Write-Output "Acceptance records: $directory"
