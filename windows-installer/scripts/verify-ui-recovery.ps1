param(
    [Parameter(Mandatory=$true)][string]$Media,
    [Parameter(Mandatory=$true)][string]$CancelledFixture,
    [Parameter(Mandatory=$true)][string]$InstalledFixture
)
$ErrorActionPreference = 'Stop'
$toolRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$mediaPath = [IO.Path]::GetFullPath($Media)
$beforePath = [IO.Path]::GetFullPath($CancelledFixture)
$afterPath = [IO.Path]::GetFullPath($InstalledFixture)
if ($beforePath -eq $afterPath) { throw 'Separate frozen cancelled and resumed fixtures are required' }
$directory = Join-Path $toolRoot ('work/ui-recovery-verify-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $directory | Out-Null
function Snapshot([string]$Command, [string]$Fixture, [string]$Name) {
    & (Join-Path $toolRoot 'runtime/dotnet/dotnet.exe') (Join-Path $toolRoot 'app/bin/Debug/net10.0-windows/OxpInstaller.dll') --cli $Command $mediaPath $Fixture
    if ($LASTEXITCODE -ne 0) { throw "Read-only task failed: $Command" }
    $transcript = Get-Content -LiteralPath (Join-Path $toolRoot 'logs/native-cli-result.txt') -Raw
    $matches = [regex]::Matches($transcript, '(?m)^OXP_UI_FS_SNAPSHOT=([^\r\n]+)')
    if ($matches.Count -ne 1 -or -not $transcript.Contains('OXP_TASK_RESULT=passed')) { throw 'Missing independent filesystem snapshot' }
    $transcript | Set-Content -LiteralPath (Join-Path $directory ($Name + '.txt')) -Encoding utf8
    return ($matches[0].Groups[1].Value | ConvertFrom-Json -AsHashtable)
}
$before = Snapshot 'ui-cancelled-verify' $beforePath 'cancelled'
$after = Snapshot 'ui-installed-verify' $afterPath 'installed'
if ($before.schema -ne 1 -or $after.schema -ne 1 -or $before.intent_id -ne $after.intent_id) { throw 'Recovery replaced the original intent' }
# Compare normalized metadata and plain filesystem UUIDs, never content hashes.
if (($before.target | ConvertTo-Json -Depth 12 -Compress) -ne ($after.target | ConvertTo-Json -Depth 12 -Compress)) { throw 'Recovery changed the GPT identity/layout' }
if ($before.formatted.Count -ne 6 -or $after.formatted.Count -ne 6) { throw 'Unexpected formatted filesystem roles' }
foreach ($role in $before.formatted.Keys) {
    if ($before.formatted[$role] -ne $after.formatted[$role]) { throw "Recovery recreated the formatted filesystem: $role" }
}
if ($before.copied.Count -ne 0 -or $after.copied.Count -ne 2) { throw 'The verified cancellation/recovery milestones differ' }
[ordered]@{passed=$true;cancelled=$beforePath;installed=$afterPath;intent_id=$before.intent_id;
    formatted_uuids=$after.formatted;root_uuids=$after.copied;
    scope='Actual UI cancellation during root-A copy followed by separately confirmed UI recovery; independent read-only before/after GPT, original formatted UUIDs and intent preserved; both roots protected, preview removed, resources and original EFI/NTFS sentinels verified. No Windows OS or physical acceptance.'} |
    ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $directory 'result.json') -Encoding utf8
Write-Output ('UI_RECOVERY_VERIFICATION=' + $directory)
