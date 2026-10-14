$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$env:DOTNET_CLI_HOME = Join-Path $projectRoot 'work/dotnet-home'
$env:NUGET_PACKAGES = Join-Path $projectRoot 'cache/nuget'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH = '0'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
& (Join-Path $projectRoot 'runtime/dotnet/dotnet.exe') build (Join-Path $projectRoot 'app/OxpInstaller.csproj') --nologo -v:minimal "-p:RestoreConfigFile=$(Join-Path $projectRoot 'app/NuGet.Config')"
if ($LASTEXITCODE -ne 0) { throw 'Windows app build failed.' }
