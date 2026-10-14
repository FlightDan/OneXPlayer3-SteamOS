param([Parameter(Mandatory=$true)][string]$DefaultRun)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
$base=[IO.Path]::GetFullPath($DefaultRun)
if(-not $base.StartsWith('E:\steamosworkspace\capacity-mock-',[StringComparison]::OrdinalIgnoreCase)){throw 'Expected the known latest default mock run'}
$result=Get-Content -LiteralPath (Join-Path $base 'evidence/result.json') -Raw | ConvertFrom-Json
if($result.passed){throw 'Do not override a successful default test'}
$components=Get-Content -LiteralPath (Join-Path $base 'evidence/components.json') -Raw | ConvertFrom-Json
$refused=@($components | Where-Object status -ne 'files_installed')
if($refused.Count -ne 2 -or @($refused | Where-Object {$_.id -ne 'flathub-ustc' -or $_.reason -ne 'Existing Flathub remote is required; add it in Discover first'}).Count){throw 'Continuation is allowed only for the reproduced optional Flathub prerequisite refusal in both slots'}
$fixtures=@(Get-ChildItem -LiteralPath (Join-Path $base 'work') -Directory -Filter 'virtual-*' | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Filter windows-fixture.qcow2 })
if($fixtures.Count -ne 1){throw 'Expected one immutable completed prepared fixture'}
$run=Join-Path 'E:\steamosworkspace' ('capacity-compatible-'+(Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path (Join-Path $run 'evidence') -Force | Out-Null
[IO.File]::WriteAllText('E:\steamosworkspace\LATEST-COMPATIBLE-CAPACITY.txt',$run)
$root=Join-Path $base 'installer'
$project=Join-Path $root ('compatible-measurement-'+(Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path $project -Force | Out-Null
$assembly=Join-Path $root 'app/bin/Debug/net10.0-windows/OxpInstaller.dll'
[IO.File]::WriteAllText((Join-Path $project 'Compatible.csproj'),('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0-windows</TargetFramework><UseWPF>true</UseWPF><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup><Reference Include="OxpInstaller"><HintPath>'+$assembly+'</HintPath></Reference></ItemGroup></Project>'))
$harness=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'capacity-mock.cs'))
$harness=$harness.Replace('namespace OxpInstaller;','using OxpInstaller;'+[Environment]::NewLine+'namespace CapacityMeasurement;')
$harness=$harness.Replace('RawImageStaging.ConvertAsync','ReflectConvertAsync').Replace('PreparedCapacity.ExpandAsync','ReflectExpandAsync')
$wrappers=@'
    private static Task ReflectConvertAsync(string source,string destination,Action<string> log,CancellationToken token) =>
        (Task)typeof(Backend).Assembly.GetType("OxpInstaller.RawImageStaging")!.GetMethod("ConvertAsync",System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic)!.Invoke(null,new object[]{source,destination,log,token})!;
    private static Task<string> ReflectExpandAsync(string image,string directory,long capacity,Action<string> log,CancellationToken token) =>
        (Task<string>)typeof(Backend).Assembly.GetType("OxpInstaller.PreparedCapacity")!.GetMethod("ExpandAsync",System.Reflection.BindingFlags.Static|System.Reflection.BindingFlags.NonPublic)!.Invoke(null,new object[]{image,directory,capacity,log,token})!;
'@
$harness=$harness.Replace('    private static readonly object Gate = new();',$wrappers+[Environment]::NewLine+'    private static readonly object Gate = new();')
[IO.File]::WriteAllText((Join-Path $project 'CapacityMock.cs'),$harness)
[IO.File]::WriteAllText((Join-Path $project 'Program.cs'),'return await CapacityMeasurement.CapacityMock.RunAsync(args[0],args[1]);')
[ordered]@{default_run=$base;default_passed=$false;scope='Separate capacity/install profile after disabling only optional flathub-ustc. The latest default Chinese selection remains failed; no production source modifications.';fixture=$fixtures[0].FullName;source_assembly=$assembly} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/profile-context.json') -Encoding utf8
Copy-Item -LiteralPath (Join-Path $base 'evidence/source-head.txt'),(Join-Path $base 'evidence/volume.json') -Destination (Join-Path $run 'evidence')
$context=Get-Content -LiteralPath (Join-Path $base 'evidence/run-context.json') -Raw | ConvertFrom-Json
$context | Add-Member -NotePropertyName default_run -NotePropertyValue $base
$context | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/run-context.json') -Encoding utf8
$sourceRoot=Split-Path $PSScriptRoot -Parent
$env:DOTNET_CLI_HOME=Join-Path $run 'build-home'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
$env:DOTNET_CLI_UI_LANGUAGE='en-US'
& (Join-Path $sourceRoot 'runtime/dotnet/dotnet.exe') build (Join-Path $project 'Compatible.csproj') --nologo -v:minimal "-p:RestoreConfigFile=$(Join-Path $root 'app/NuGet.Config')" 2>&1 | Tee-Object -FilePath (Join-Path $run 'evidence/measurement-build.log')
if($LASTEXITCODE -ne 0){throw 'Compatible measurement build failed'}
Write-Output ('COMPATIBLE_RUN='+$run)
& (Join-Path $root 'runtime/dotnet/dotnet.exe') (Join-Path $project 'bin/Debug/net10.0-windows/Compatible.dll') $run ('prepared-qcow:'+$fixtures[0].FullName) 2>&1 | Tee-Object -FilePath (Join-Path $run 'evidence/process-output.log')
$code=$LASTEXITCODE
Get-Content -LiteralPath (Join-Path $run 'evidence/result.json')
if($code -ne 0){throw 'Compatible profile failed; retain all evidence'}
