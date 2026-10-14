param([Parameter(Mandatory=$true)][string]$Run,[Parameter(Mandatory=$true)][int]$WorkerPid)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($Run)
if($root -ne 'E:\steamosworkspace\capacity-compatible-20261014-030452'){throw 'Only the known compatible measurement worker is authorized'}
$deadline=[DateTime]::UtcNow.AddMinutes(12)
while([DateTime]::UtcNow -lt $deadline){
    if(Test-Path -LiteralPath (Join-Path $root 'evidence/result.json')){throw 'Worker already ended; do not interrupt'}
    $last=Get-Content -LiteralPath (Join-Path $root 'evidence/events.jsonl') -Tail 2 -ErrorAction SilentlyContinue
    $atReadOnlyCheck=$false
    foreach($line in $last){try{$row=$line|ConvertFrom-Json; if($row.stage -eq '11-installed-filesystem-usage' -or $row.name -eq '11-installed-filesystem-usage'){$atReadOnlyCheck=$true}}catch{}}
    if($atReadOnlyCheck){
        $worker=Get-CimInstance Win32_Process -Filter ('ProcessId='+$WorkerPid)
        if(-not $worker -or $worker.Name -ne 'dotnet.exe' -or -not $worker.CommandLine.Contains($root)){throw 'Worker identity changed'}
        $stages=Get-Content -LiteralPath (Join-Path $root 'evidence/stages.json') -Raw | ConvertFrom-Json
        if(-not @($stages|Where-Object {$_.name -eq '10-physical-source-readiness' -and $_.passed}).Count){throw 'Source readiness did not pass'}
        [Diagnostics.Process]::GetProcessById($WorkerPid).Kill($true)
        [IO.File]::WriteAllText((Join-Path $root 'evidence/STOPPED-FOR-LATEST-NATIVE-SNAPSHOT.txt'),'Stopped during the extra read-only filesystem-usage measurement, before native target creation. All preparation, 27 components in each slot, readonly verification, rEFInd, selected capacity and source readiness passed. Continue with latest native code; all logs retained. UTC: '+[DateTime]::UtcNow.ToString('o'))
        exit 0
    }
    Start-Sleep -Milliseconds 200
}
throw 'Cutover wait timed out; no process stopped'
