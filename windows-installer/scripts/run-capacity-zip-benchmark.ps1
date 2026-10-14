param([Parameter(Mandatory=$true)][string]$Run)
$ErrorActionPreference='Stop'
$runPath=[IO.Path]::GetFullPath($Run)
if (-not $runPath.StartsWith('E:\steamosworkspace\capacity-mock-',[StringComparison]::OrdinalIgnoreCase)) { throw 'Expected a retained capacity mock run' }
$mainResult=Get-Content -LiteralPath (Join-Path $runPath 'evidence/result.json') -Raw | ConvertFrom-Json
if (-not $mainResult.passed) { throw 'Complete the native installation measurement first' }
$project=Join-Path $runPath 'installer/zip-benchmark'
if (Test-Path -LiteralPath $project) { throw 'Existing benchmark evidence must not be overwritten' }
New-Item -ItemType Directory -Path $project -Force | Out-Null
$projectText=@'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0-windows</TargetFramework><UseWPF>true</UseWPF><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup>
  <ItemGroup><Reference Include="OxpInstaller"><HintPath>../app/bin/Debug/net10.0-windows/OxpInstaller.dll</HintPath></Reference></ItemGroup>
</Project>
'@
[IO.File]::WriteAllText((Join-Path $project 'ZipBenchmark.csproj'),$projectText)
$program=@'
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using OxpInstaller;

var run = args[0];
var evidence = Path.Combine(run,"evidence");
var workspace = Path.Combine(run,"zip-benchmark-work");
var previous = InstallerWorkspace.DirectoryPath;
InstallerWorkspace.Select(workspace);
using var writer = new StreamWriter(Path.Combine(evidence,"default-zip-events.jsonl")) { AutoFlush=true };
using var transcript = new StreamWriter(Path.Combine(evidence,"default-zip-full.log")) { AutoFlush=true };
var clock = Stopwatch.StartNew();
void Record(object e) => writer.WriteLine(JsonSerializer.Serialize(e));
try {
    var origin = AriaDownload.Origins()[0];
    if (!origin.Url.EndsWith(".img.zip")) throw new IOException("Latest default source is not ZIP");
    var job = await AriaDownload.CreateAsync(origin.Url,CancellationToken.None);
    Record(new {type="probe",seconds=clock.Elapsed.TotalSeconds,job});
    var startDownload = clock.Elapsed.TotalSeconds;
    job = await AriaDownload.RunAsync(job,p=>Record(new{type="download_progress",utc=DateTime.UtcNow,seconds=clock.Elapsed.TotalSeconds,p.Completed,p.Total,p.Speed,p.Status}),CancellationToken.None);
    var downloadSeconds = clock.Elapsed.TotalSeconds-startDownload;
    var startExtract=clock.Elapsed.TotalSeconds;
    var image = await Backend.ImportAsync(AriaDownload.ResultPath(job),text=>{transcript.WriteLine(text);Record(new{type="extract_log",utc=DateTime.UtcNow,seconds=clock.Elapsed.TotalSeconds,text});},CancellationToken.None);
    var extractSeconds=clock.Elapsed.TotalSeconds-startExtract;
    File.WriteAllText(Path.Combine(evidence,"default-zip-benchmark.json"),JsonSerializer.Serialize(new{passed=true,source=origin.Url,archive_bytes=job.Remote.Length,download_seconds=downloadSeconds,extract_seconds=extractSeconds,image_bytes=new FileInfo(image).Length,image,workspace,scope="Latest application's default official ZIP downloaded and imported through AriaDownload and Backend.ImportAsync after primary mock run; no system deployment repeated."},new JsonSerializerOptions{WriteIndented=true}));
    Console.WriteLine(File.ReadAllText(Path.Combine(evidence,"default-zip-benchmark.json")));
} catch(Exception error) {
    File.WriteAllText(Path.Combine(evidence,"default-zip-benchmark.json"),JsonSerializer.Serialize(new{passed=false,error=error.ToString(),seconds=clock.Elapsed.TotalSeconds},new JsonSerializerOptions{WriteIndented=true}));
    throw;
} finally { InstallerWorkspace.Select(previous); }
'@
[IO.File]::WriteAllText((Join-Path $project 'Program.cs'),$program)
$sourceRoot=Split-Path $PSScriptRoot -Parent
$env:DOTNET_CLI_HOME=Join-Path $runPath 'build-home'
$env:NUGET_PACKAGES=Join-Path $runPath 'build-nuget'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
& (Join-Path $sourceRoot 'runtime/dotnet/dotnet.exe') build (Join-Path $project 'ZipBenchmark.csproj') --nologo -v:minimal "-p:RestoreConfigFile=$(Join-Path $runPath 'installer/app/NuGet.Config')" 2>&1 | Tee-Object -FilePath (Join-Path $runPath 'evidence/default-zip-benchmark-build.log')
if($LASTEXITCODE -ne 0){throw 'ZIP benchmark build failed'}
& (Join-Path $runPath 'installer/runtime/dotnet/dotnet.exe') (Join-Path $project 'bin/Debug/net10.0-windows/ZipBenchmark.dll') $runPath 2>&1 | Tee-Object -FilePath (Join-Path $runPath 'evidence/default-zip-process.log')
if($LASTEXITCODE -ne 0){throw 'ZIP benchmark failed; all logs retained'}
