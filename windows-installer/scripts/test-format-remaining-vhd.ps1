# Actual NTFS formatting only inside a newly created, uniquely named disposable VHDX.
param([switch]$Helper, [switch]$AlignRight, [ValidateSet('Debug','Release')][string]$Configuration = 'Release')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskDir=Join-Path $taskRoot ('work/ntfs-vhd-check-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskDir | Out-Null
$taskVhd=Join-Path $taskDir 'fixture.vhdx'
$taskMounted=$false
try {
    New-VHD -Path $taskVhd -Dynamic -SizeBytes 512GB -BlockSizeBytes 1MB -LogicalSectorSizeBytes 512 -ErrorAction Stop | Out-Null
    Mount-VHD -Path $taskVhd -NoDriveLetter | Out-Null; $taskMounted=$true
    $taskDisk=@(Get-DiskImage -ImagePath $taskVhd | Get-Disk)
    if($taskDisk.Count -ne 1 -or $taskDisk[0].IsBoot -or $taskDisk[0].IsSystem -or $taskDisk[0].Size -ne 512GB -or [string]$taskDisk[0].BusType -notin @('File Backed Virtual','FileBackedVirtual')){throw 'Not the owned disposable VHD.'}
    $taskNumber=$taskDisk[0].Number
    Initialize-Disk -Number $taskNumber -PartitionStyle GPT | Out-Null
    $taskKeep=New-Partition -DiskNumber $taskNumber -Offset 32MB -Size 512MB -GptType '{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}' -ErrorAction Stop
    $taskKeepVolume=Format-Volume -Partition $taskKeep -FileSystem NTFS -NewFileSystemLabel 'NTFS_TEST_KEEP' -Confirm:$false
    $taskSentinel=$taskKeepVolume.Path+'preserved.txt'
    [IO.File]::WriteAllText($taskSentinel,'preserve this VHD fixture data')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'format-remaining.ps1') -Destination (Join-Path $taskDir 'format-remaining.ps1')
    # Adapt only the inventory bus of this exact owned VHD for the physical-script test.
    # The production script continues to reject virtual disks in normal operation.
    $taskRead=Join-Path $PSScriptRoot 'read-disks.ps1'
    $taskAdapter=@'
$ErrorActionPreference='Stop'
$image=Get-DiskImage -ImagePath '__VHD__'
if(-not $image.Attached){throw 'Fixture detached'}
$bound=@($image|Get-Disk)
if($bound.Count -ne 1 -or $bound[0].IsBoot -or $bound[0].IsSystem -or $bound[0].Size -ne 512GB -or [string]$bound[0].BusType -notin @('File Backed Virtual','FileBackedVirtual')){throw 'Fixture binding changed'}
$data=@(((& '__READ__')|ConvertFrom-Json)|Where-Object number -eq $bound[0].Number)
if($data.Count -ne 1){throw 'Missing fixture inventory'}
$data[0].bus='NVMe'
ConvertTo-Json -InputObject $data -Depth 8
'@
    $taskAdapter.Replace('__VHD__',$taskVhd.Replace("'","''")).Replace('__READ__',$taskRead.Replace("'","''")) | Set-Content (Join-Path $taskDir 'read-disks.ps1')
    $taskSnapshot=& (Join-Path $taskDir 'read-disks.ps1')
    $taskRequest=Join-Path $taskDir 'format-request.json'
    @{Selection=@{Snapshot=$taskSnapshot;Example=$false;Disk=$taskNumber;Start=544MB;Capacity=64GB;AlignRight=[bool]$AlignRight};Language='en-US'}|ConvertTo-Json -Depth 10|Set-Content $taskRequest
    if ($Helper) {
        # Isolate Backend.Root and its inventory adapter from the installed tool.
        # The runner loads the actual release assembly and confirms only this owned fixture.
        $taskScripts=Join-Path $taskDir 'scripts'
        $taskWork=Join-Path $taskDir 'work'
        $taskRunner=Join-Path $taskDir 'helper-runner'
        New-Item -ItemType Directory -Path $taskScripts,$taskWork,$taskRunner,(Join-Path $taskDir 'guest') | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $taskDir 'components') | Out-Null
        Copy-Item -LiteralPath (Join-Path $taskRoot 'components/i18n') -Destination (Join-Path $taskDir 'components/i18n') -Recurse
        Copy-Item -LiteralPath (Join-Path $taskDir 'format-remaining.ps1'),(Join-Path $taskDir 'read-disks.ps1') -Destination $taskScripts
        $taskRequest=Join-Path $taskWork 'format-request.json'
        @{Selection=@{Snapshot=$taskSnapshot;Example=$false;Disk=$taskNumber;Start=544MB;Capacity=64GB;AlignRight=[bool]$AlignRight};Language='en-US'}|ConvertTo-Json -Depth 10|Set-Content $taskRequest
        $taskProject=@'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>WinExe</OutputType><TargetFramework>net10.0-windows</TargetFramework><UseWPF>true</UseWPF><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup><Reference Include="OxpInstaller"><HintPath>__ASSEMBLY__</HintPath></Reference></ItemGroup></Project>
'@
        $taskAssembly=Join-Path $taskRoot "app/bin/$Configuration/net10.0-windows/OxpInstaller.dll"
        if (!(Test-Path -LiteralPath $taskAssembly)) { throw 'Build the release assembly before the helper fixture check.' }
        $taskProject.Replace('__ASSEMBLY__',[Security.SecurityElement]::Escape($taskAssembly)) | Set-Content (Join-Path $taskRunner 'FixtureRunner.csproj')
        @'
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using OxpInstaller;
public sealed class FixtureRunner : Application
{
    [STAThread] public static void Main(string[] args)
    {
        var application = new FixtureRunner { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        application.Startup += async (_, _) => {
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
            bool confirmationSeen = false;
            timer.Tick += (_, _) => {
                var window = application.Windows.Cast<Window>().SingleOrDefault(w => w.Title.StartsWith("Format remaining space (Beta", StringComparison.Ordinal));
                if (window?.Content is not ScrollViewer { Content: StackPanel panel }) return;
                var consent = panel.Children.OfType<CheckBox>().Single();
                var button = panel.Children.OfType<WrapPanel>().Single().Children.OfType<Button>().Single(b => b.Name == "FormatConfirm");
                consent.IsChecked = true;
                if (!button.IsEnabled) throw new IOException("Owned fixture consent did not enable confirmation.");
                confirmationSeen = true; timer.Stop(); button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            };
            timer.Start();
            try {
                var result = await RemainingSpaceFormat.ExecuteHelperAsync(args[0]);
                if (result != 0 || !confirmationSeen) throw new IOException("Helper failed or did not show its confirmation: " + result);
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(args[0])!, "helper-proof.txt"), "actual-release-ExecuteHelperAsync-admin-request-lock-plan-validation-WPF-consent-production-PowerShell-format:passed");
                application.Shutdown(0);
            } catch (Exception error) {
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(args[0])!, "helper-failure.txt"), error.ToString());
                application.Shutdown(1);
            } finally { timer.Stop(); }
        };
        application.Run();
    }
}
'@ | Set-Content (Join-Path $taskRunner 'Program.cs')
        $taskDotnet=Join-Path $taskRoot 'runtime/dotnet/dotnet.exe'
        & $taskDotnet build (Join-Path $taskRunner 'FixtureRunner.csproj') -c Release --nologo | Set-Content (Join-Path $taskDir 'helper-build.txt')
        if ($LASTEXITCODE -ne 0) { throw "Helper fixture runner build failed: $taskDir/helper-build.txt" }
        & $taskDotnet (Join-Path $taskRunner 'bin/Release/net10.0-windows/FixtureRunner.dll') $taskRequest
        if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath (Join-Path $taskWork 'helper-proof.txt'))) { throw "Actual helper failed: inspect $taskWork" }
    } else {
        & (Join-Path $taskDir 'format-remaining.ps1') -RequestPath $taskRequest -ValidateOnly
        & (Join-Path $taskDir 'format-remaining.ps1') -RequestPath $taskRequest
    }
    if([IO.File]::ReadAllText($taskSentinel) -ne 'preserve this VHD fixture data'){throw 'Existing fixture data changed'}
    $taskResult=Get-Content (Join-Path (Split-Path $taskRequest -Parent) 'format-result.json') -Raw|ConvertFrom-Json
    $taskNew=@(Get-Partition -DiskNumber $taskNumber|Where-Object { [guid]$_.Guid -eq [guid]$taskResult.partitionGuid })
    $taskVolume=$taskNew[0]|Get-Volume
    $taskExpectedOffset=if($AlignRight){544MB}else{544MB+64GB}
    if($taskNew.Count -ne 1 -or $taskResult.phase -ne 'verified' -or $taskNew[0].Offset -ne $taskExpectedOffset -or $taskNew[0].Offset % 4096 -ne 0 -or $taskVolume.FileSystemType -ne 'NTFS' -or $taskVolume.AllocationUnitSize -ne 4096){throw 'NTFS VHD verification failed'}
    $taskFormattedSnapshot=& (Join-Path $taskDir 'read-disks.ps1')
    $taskFormattedSnapshot | Set-Content (Join-Path $taskDir 'formatted-snapshot.json')
    [IO.File]::WriteAllText($taskVolume.Path+'shared-file.txt','shared NTFS fixture data')
    if([IO.File]::ReadAllText($taskVolume.Path+'shared-file.txt') -ne 'shared NTFS fixture data'){throw 'Shared NTFS file readback failed'}
    if($taskNew[0].Size -ne 512GB-1MB-(544MB+64GB)){throw 'SteamOS reservation or NTFS remainder differs'}
    $taskReserved=if($AlignRight){512GB-1MB-($taskNew[0].Offset+$taskNew[0].Size)}else{$taskNew[0].Offset-544MB}
    if($taskReserved -ne 64GB){throw 'SteamOS reserved gap differs'}
    @{passed=$true;helperPathVerified=[bool]$Helper;alignRight=[bool]$AlignRight;configuration=$Configuration;diskFile=$taskVhd;start=$taskNew[0].Offset;bytes=$taskNew[0].Size;filesystem='NTFS';clusterBytes=4096;reservedSteamOSBytes=64GB;sharedFileReadback=$true;existingDataPreserved=$true;scope='512 GiB owned dynamic VHD, production format script with an inventory adapter bound to this newly created VHD; no physical disk writes.'}|ConvertTo-Json|Set-Content (Join-Path $taskDir 'result.json')
    Write-Output "Passed actual NTFS VHD check: $taskDir"
} finally { if($taskMounted){Dismount-VHD -Path $taskVhd} }
