param([string]$OldProject='D:\steamosmod', [string]$NewProject='C:\steamosmod')
$ErrorActionPreference='Stop'
$project=[IO.Path]::GetFullPath($NewProject)
$old=[IO.Path]::GetFullPath($OldProject)
$root=Join-Path $project 'windows-installer'
$work=Join-Path $root 'work'
$qemu=Join-Path $root 'runtime/qemu-min/qemu-img.exe'
if (Get-Process -Name qemu-system-x86_64,qemu-img -ErrorAction SilentlyContinue) { throw 'Stop QEMU before relocation' }
function Ordinary([string]$Path, [string]$Scope) {
    $full=[IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($Scope+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes intended project scope' }
    $entry=Get-Item -LiteralPath $full
    while ($entry -and $entry.FullName.Length -ge $Scope.Length) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected project path' }
        $entry=if ($entry.PSIsContainer) { $entry.Parent } else { $entry.Directory }
    }
}
$folder=Join-Path $root ('logs/relocation-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $folder | Out-Null
$docs=@()
foreach ($name in @('RESEARCH_GOAL.md','WINDOWS_INSTALLER_PLAN.md','DEVICE_CHANGES.md','RESEARCH_RESULTS.md','SteamOS-工作记录.md')) {
    $before=Join-Path $old $name; $after=Join-Path $project $name
    if (-not (Test-Path -LiteralPath $before)) { continue }
    if ((Test-Path -LiteralPath $after) -and (Get-Item -LiteralPath $after).LastWriteTime -ge (Get-Item -LiteralPath $before).LastWriteTime) { continue }
    if (Test-Path -LiteralPath $after) { Ordinary $after $project; Copy-Item -LiteralPath $after -Destination (Join-Path $folder ('before-'+$name)) }
    Copy-Item -LiteralPath $before -Destination $after -Force
    $docs += $name
}
$records=@()
$oldPrefix=(Join-Path $old 'windows-installer')+[IO.Path]::DirectorySeparatorChar
foreach ($file in Get-ChildItem -LiteralPath $work -Recurse -File -Filter '*.qcow2') {
    Ordinary $file.FullName $work
    $info=(& $qemu info -f qcow2 --output=json $file.FullName) -join [Environment]::NewLine | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect qcow2 metadata' }
    $base=$info.'backing-filename'
    if (-not $base -or -not $base.StartsWith($oldPrefix,[StringComparison]::OrdinalIgnoreCase)) { continue }
    $newBase=Join-Path $root $base.Substring($oldPrefix.Length)
    $record=[ordered]@{image=$file.FullName;old_backing=$base;new_backing=$newBase;format=$info.'backing-filename-format';status='planned'}
    $records += $record
    if (-not (Test-Path -LiteralPath $newBase)) { $record.status='historical-backing-retired'; continue }
    Ordinary $newBase $root
    if ($info.'dirty-flag' -or $info.'format-specific'.data.corrupt) { $record.status='needs-structure-review'; continue }
    if ($record.format -notin @('raw','qcow2')) { throw 'Unsupported backing format' }
    $relative=[IO.Path]::GetRelativePath($file.DirectoryName,$newBase)
    $record.relative_backing=$relative
    $records | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $folder 'backing-migration.json') -Encoding utf8
    # Only relocate the backing reference of the user's moved project files.
    # Payload sectors are unchanged; old/new filesystem identities are verified
    # separately. Missing retired historical bases are never guessed.
    & $qemu rebase -u -f qcow2 -F $record.format -b $relative $file.FullName
    if ($LASTEXITCODE -ne 0) { throw 'Backing relocation failed; see saved original reference' }
    $check=(& $qemu info -f qcow2 --output=json $file.FullName) -join [Environment]::NewLine | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $check.'backing-filename' -ne $relative -or $check.'virtual-size' -ne $info.'virtual-size') { throw 'Relocated metadata mismatch' }
    $record.status='reference-relocated'
}
$records | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $folder 'backing-migration.json') -Encoding utf8
[ordered]@{old_project=$old;new_project=$project;restored_docs=$docs;relocated=@($records | Where-Object status -eq 'reference-relocated').Count;retired_historical=@($records | Where-Object status -eq 'historical-backing-retired').Count;needs_review=@($records | Where-Object status -eq 'needs-structure-review').Count;scope='Move-related path metadata only; old root docs preserved, newer D records copied to C. No device access or content hash.'} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $folder 'result.json') -Encoding utf8
Write-Output ('RELOCATION_RESULT='+$folder)
