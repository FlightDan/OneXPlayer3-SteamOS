param([Parameter(Mandatory=$true)][string]$Fixture)
$ErrorActionPreference = 'Stop'
$toolRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workRoot = [IO.Path]::GetFullPath((Join-Path $toolRoot 'work')) + [IO.Path]::DirectorySeparatorChar
$source = [IO.Path]::GetFullPath($Fixture)
if (-not $source.StartsWith($workRoot, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetExtension($source) -ne '.qcow2') {
    throw 'Only this tool''s work-directory qcow2 fixture can be compacted'
}
# Reject redirected ancestors as well as the final file.
$ancestor = Get-Item -LiteralPath $source
while ($ancestor -and $ancestor.FullName.Length -ge $toolRoot.Length) {
    if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected fixture path' }
    $ancestor = if ($ancestor.PSIsContainer) { $ancestor.Parent } else { $ancestor.Directory }
}
$marker = Get-Content -LiteralPath ([IO.Path]::ChangeExtension($source, '.fixture.json')) -Raw | ConvertFrom-Json
if ($marker.kind -ne 'oxp3-virtual-fixture' -or $marker.size -ne 80GB) { throw 'Fixture ownership/size mismatch' }
$qemuImg = Join-Path $toolRoot 'runtime/qemu-min/qemu-img.exe'
function RequireStopped {
    if (Get-Process -Name qemu-system-x86_64 -ErrorAction SilentlyContinue) { throw 'Stop QEMU before fixture compaction' }
}
RequireStopped
$info = (& $qemuImg info -f qcow2 --output=json $source) -join "`n" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $info.'virtual-size' -ne 80GB -or $info.'backing-filename' -or $info.snapshots -or $info.'dirty-flag' -or $info.'format-specific'.data.'data-file') {
    throw 'Only clean standalone fixtures without snapshots/external data are supported'
}
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporary = [IO.Path]::GetFullPath((Join-Path $tempBase ('oxp3-fixture-compaction/' + [guid]::NewGuid().ToString('N'))))
if (-not $temporary.StartsWith($tempBase.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe temporary directory' }
New-Item -ItemType Directory -Path $temporary | Out-Null
$compressed = Join-Path $temporary 'compressed.qcow2'
$backup = Join-Path $temporary 'original.qcow2'
$journal = Join-Path $toolRoot ('logs/fixture-compaction-' + [guid]::NewGuid().ToString('N') + '.json')
$record = [ordered]@{schema=1; source=$source; original_backup=$backup; temporary=$compressed; before_bytes=(Get-Item -LiteralPath $source).Length; phase='converting'; comparison='logical-byte-comparison-no-content-hash'; documentation='https://www.qemu.org/docs/master/tools/qemu-img.html'}
function SaveRecord { $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $journal -Encoding utf8 }
SaveRecord
& $qemuImg convert -f qcow2 -O qcow2 -c -o compression_type=zstd $source $compressed
if ($LASTEXITCODE -ne 0) { throw 'Conversion failed; original preserved' }
& $qemuImg check -f qcow2 $compressed
if ($LASTEXITCODE -ne 0) { throw 'Compressed qcow2 structure failed; original preserved' }
$newInfo = (& $qemuImg info -f qcow2 --output=json $compressed) -join "`n" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $newInfo.'virtual-size' -ne $info.'virtual-size' -or $newInfo.'backing-filename') { throw 'Compressed geometry/backing mismatch' }
& $qemuImg compare -f qcow2 -F qcow2 $source $compressed
if ($LASTEXITCODE -ne 0) { throw 'Logical contents differ; original preserved' }
$record.after_bytes = (Get-Item -LiteralPath $compressed).Length
if ($record.after_bytes -ge $record.before_bytes) { throw 'No space saved; original preserved' }
RequireStopped
$record.phase='verified-moving-original'; SaveRecord
# Both absolute targets were checked above. Keep the original in our private
# temporary directory; preserve the fixture's public path and all child backings.
Move-Item -LiteralPath $source -Destination $backup
$record.phase='original-backed-up'; SaveRecord
try { Move-Item -LiteralPath $compressed -Destination $source }
catch {
    if (-not (Test-Path -LiteralPath $source)) { Move-Item -LiteralPath $backup -Destination $source }
    throw
}
$record.phase='installed-original-retained'; $record.saved_bytes=$record.before_bytes-$record.after_bytes; SaveRecord
Write-Output ('COMPACTION_RESULT=' + $journal)
Write-Output ('SAVED_BYTES=' + $record.saved_bytes)
