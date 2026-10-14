param([string]$Destination='E:\steamosworkspace',[ValidateSet('zip','bz2')][string]$RecoveryFormat='zip',[string]$PreparedImage)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
$sourceRoot=Split-Path $PSScriptRoot -Parent
$base=[IO.Path]::GetFullPath($Destination)
if ($base -ne 'E:\steamosworkspace') { throw 'This measurement is scoped to E:\steamosworkspace' }
if($PreparedImage){
    $PreparedImage=[IO.Path]::GetFullPath($PreparedImage)
    if(-not $PreparedImage.StartsWith('E:\steamosworkspace\capacity-compatible-20261014-030452\work\',[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($PreparedImage) -ne 'prepared.img'){throw 'Only the verified compatible-profile image may be reused'}
    $priorRun='E:\steamosworkspace\capacity-compatible-20261014-030452'
    if(-not(Test-Path -LiteralPath (Join-Path $priorRun 'evidence/STOPPED-FOR-LATEST-NATIVE-SNAPSHOT.txt'))){throw 'Old worker must be stopped before cutover'}
    $priorStages=Get-Content -LiteralPath (Join-Path $priorRun 'evidence/stages.json') -Raw | ConvertFrom-Json
    foreach($name in '06-compatible-components','07-components-readonly-verify','08-refind-install','09-selected-64gib-capacity','10-physical-source-readiness'){
        if(-not @($priorStages | Where-Object {$_.name -eq $name -and $_.passed}).Count){throw ('Required prior stage missing: '+$name)}
    }
    $priorComponents=Get-Content -LiteralPath (Join-Path $priorRun 'evidence/components.json') -Raw | ConvertFrom-Json
    if($priorComponents.Count -ne 54 -or @($priorComponents | Where-Object status -ne 'files_installed').Count){throw 'Compatible profile components were not all accepted'}
}
$stamp=Get-Date -Format yyyyMMdd-HHmmss
$run=Join-Path $base ('capacity-mock-'+$stamp)
if (Test-Path -LiteralPath $run) { throw 'Existing evidence must not be overwritten' }
New-Item -ItemType Directory -Path (Join-Path $run 'evidence'),(Join-Path $run 'inputs'),(Join-Path $run 'work/steamos-3.10') -Force | Out-Null
$root=Join-Path $run 'installer'
New-Item -ItemType Directory -Path $root -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $run 'evidence/orchestration-transcript.log') | Out-Null
[IO.File]::WriteAllText((Join-Path $base 'LATEST-CAPACITY-MOCK.txt'),$run)
$preparation=[Diagnostics.Stopwatch]::StartNew()
$preStages=[Collections.Generic.List[object]]::new()
function Stage([string]$name,[scriptblock]$action) {
    $start=$preparation.Elapsed.TotalSeconds
    Write-Output ('STAGE_START='+$name)
    & $action
    $end=$preparation.Elapsed.TotalSeconds
    $preStages.Add([ordered]@{name=$name;start_seconds=$start;end_seconds=$end;duration_seconds=$end-$start})
    $preStages | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $run 'evidence/preparation-stages.json') -Encoding utf8
    Write-Output ('STAGE_END='+$name)
}
function Copy-Tree([string]$from,[string]$to) {
    New-Item -ItemType Directory -Path $to -Force | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath $from -Recurse -File | Where-Object { $_.FullName -notmatch '(^|[\\/])__pycache__([\\/]|$)' -and $_.Extension -ne '.pyc' }) {
        $target=Join-Path $to ([IO.Path]::GetRelativePath($from,$file.FullName))
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target
    }
}
try {
    Stage '00-copy-isolated-source-and-portable-runtime' {
        New-Item -ItemType Directory -Path (Join-Path $root 'app') -Force | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'app') -File | Copy-Item -Destination (Join-Path $root 'app')
        foreach ($name in 'guest','components','scripts','licenses') { Copy-Tree (Join-Path $sourceRoot $name) (Join-Path $root $name) }
        foreach ($name in 'qemu-min','alpine/boot','archive','desync','aria2','console','payload') { Copy-Tree (Join-Path $sourceRoot "runtime/$name") (Join-Path $root "runtime/$name") }
        foreach ($name in 'host/fxr','shared') { Copy-Tree (Join-Path $sourceRoot "runtime/dotnet/$name") (Join-Path $root "runtime/dotnet/$name") }
        Copy-Item -LiteralPath (Join-Path $sourceRoot 'runtime/dotnet/dotnet.exe') -Destination (Join-Path $root 'runtime/dotnet/dotnet.exe')
        foreach ($name in 'integration','plugins','components/waydroid') { Copy-Tree (Join-Path $sourceRoot "cache/$name") (Join-Path $root "cache/$name") }
        Copy-Item -LiteralPath (Join-Path $sourceRoot 'cache/alpine-virt-3.23.6-x86_64.iso') -Destination (Join-Path $root 'cache/alpine-virt-3.23.6-x86_64.iso')
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'capacity-mock.cs') -Destination (Join-Path $root 'app/CapacityMock.cs')
        foreach ($name in 'capacity-check.sh','capacity-check.py') { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $root ('guest/'+$name.Replace('capacity-check','capacity-usage'))) }
        $usagePath=Join-Path $root 'guest/capacity-usage.sh'
        [IO.File]::WriteAllText($usagePath,[IO.File]::ReadAllText($usagePath).Replace('capacity-check.py','capacity-usage.py'))
        $backendPath=Join-Path $root 'app/Backend.cs'
        [IO.File]::WriteAllText($backendPath,[IO.File]::ReadAllText($backendPath).Replace('task is not ("resize-prepared"','task is not ("capacity-usage" or "resize-prepared"'))
        $appPath=Join-Path $root 'app/App.xaml.cs'
        $appText=[IO.File]::ReadAllText($appPath)
        $entry='if (e.Args.Length == 3 && e.Args[0] == "--capacity-mock") { Shutdown(await CapacityMock.RunAsync(e.Args[1], e.Args[2])); return; }'
        [IO.File]::WriteAllText($appPath,$appText.Replace('base.OnStartup(e);',('base.OnStartup(e);'+[Environment]::NewLine+'        '+$entry)))
        & git -c safe.directory=C:/steamosmod -C (Split-Path $sourceRoot -Parent) status --short | Set-Content -LiteralPath (Join-Path $run 'evidence/source-git-status.txt')
        & git -c safe.directory=C:/steamosmod -C (Split-Path $sourceRoot -Parent) rev-parse HEAD | Set-Content -LiteralPath (Join-Path $run 'evidence/source-head.txt')
        & git -c safe.directory=C:/steamosmod -C (Split-Path $sourceRoot -Parent) diff -- windows-installer/app windows-installer/guest windows-installer/components windows-installer/scripts | Set-Content -LiteralPath (Join-Path $run 'evidence/source-tracked-diff.patch')
        Get-ChildItem -LiteralPath (Join-Path $root 'app'),(Join-Path $root 'components'),(Join-Path $root 'guest') -Recurse -File | Select-Object FullName,Length,LastWriteTimeUtc | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $run 'evidence/source-snapshot-files.json')
    }
    Stage '01-application-build' {
        $env:DOTNET_CLI_HOME=Join-Path $run 'build-home'
        $env:NUGET_PACKAGES=Join-Path $run 'build-nuget'
        $env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
        $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1'
        $env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
        $env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='0'
        $env:DOTNET_CLI_UI_LANGUAGE='en-US'
        & (Join-Path $sourceRoot 'runtime/dotnet/dotnet.exe') build (Join-Path $root 'app/OxpInstaller.csproj') --nologo -v:minimal "-p:RestoreConfigFile=$(Join-Path $root 'app/NuGet.Config')" 2>&1 | Tee-Object -FilePath (Join-Path $run 'evidence/application-build.log')
        if ($LASTEXITCODE -ne 0) { throw 'Isolated instrumented build failed' }
    }
    if(-not $PreparedImage -and $RecoveryFormat -eq 'bz2') { Stage '02-copy-recovery-archive' {
        Copy-Item -LiteralPath (Join-Path $sourceRoot 'cache/steamdeck-oobe-repair-20260707.10-3.8.14.img.bz2') -Destination (Join-Path $run 'inputs/recovery.img.bz2')
    } }
    if(-not $PreparedImage){ Stage '03-seed-existing-official-root-cache' {
        foreach ($name in 'rootfs.img','complete.txt') { Copy-Item -LiteralPath (Join-Path $sourceRoot "work/steamos-3.10/$name") -Destination (Join-Path $run "work/steamos-3.10/$name") }
        [ordered]@{cached=$true;source='Existing local Valve SteamOS 3.10 build20260924.1000 rootfs cache';official_root_network_download_measured=$false;recovery_archive_format=$RecoveryFormat;recovery_archive_bytes=$(if($RecoveryFormat -eq 'bz2'){(Get-Item (Join-Path $run 'inputs/recovery.img.bz2')).Length}else{0});rootfs_bytes=(Get-Item (Join-Path $run 'work/steamos-3.10/rootfs.img')).Length;started_local=(Get-Date -Format o);sdk_path=(Join-Path $sourceRoot 'runtime/dotnet');run=$run} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/run-context.json') -Encoding utf8
        Get-Volume -DriveLetter E | Select-Object DriveLetter,FileSystem,AllocationUnitSize,Size,SizeRemaining | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/volume.json')
        Get-CimInstance Win32_DiskDrive | Select-Object Index,Model,InterfaceType,Size | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/host-disks.json')
    } } else {
        $priorContext=Get-Content -LiteralPath (Join-Path $priorRun 'evidence/run-context.json') -Raw | ConvertFrom-Json
        $priorContext | Add-Member -NotePropertyName compatible_run -NotePropertyValue $priorRun
        $priorContext.run=$run
        $priorContext | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/run-context.json') -Encoding utf8
        Copy-Item -LiteralPath (Join-Path $priorRun 'evidence/components.json'),(Join-Path $priorRun 'evidence/volume.json') -Destination (Join-Path $run 'evidence')
        [ordered]@{image=$PreparedImage;compatible_run=$priorRun;default_run=$priorContext.default_run;scope='Latest native source snapshot; unchanged preparatory backend and component files reused only after their successful stages. Old worker stopped before native target creation.'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'evidence/latest-native-cutover.json')
    }
    Write-Output ('RUN='+$run)
    $recoveryInput=if($PreparedImage){'ready-image:'+$PreparedImage}elseif($RecoveryFormat -eq 'zip'){'default-zip'}else{Join-Path $run 'inputs/recovery.img.bz2'}
    & (Join-Path $root 'runtime/dotnet/dotnet.exe') (Join-Path $root 'app/bin/Debug/net10.0-windows/OxpInstaller.dll') --capacity-mock $run $recoveryInput 2>&1 | Tee-Object -FilePath (Join-Path $run 'evidence/process-output.log')
    $code=$LASTEXITCODE
    Get-Content -LiteralPath (Join-Path $run 'evidence/result.json')
    if ($code -ne 0) { throw 'Capacity mock failed; all evidence retained' }
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $run 'evidence/orchestration-error.txt')
    throw
} finally { Stop-Transcript | Out-Null }
