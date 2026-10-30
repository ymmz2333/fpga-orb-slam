param(
    [Parameter(Position=0)][ValidateSet('exec','start','status','wait','log','list','check','shell')]
    [string]$Action = 'check',
    [Parameter(Position=1)][string]$Value,
    [string]$Name = 'task',
    [ValidateRange(0,60)][int]$Seconds = 30,
    [ValidateRange(1,100)][int]$Lines = 20,
    [ValidateRange(200,12000)][int]$MaxChars = 4000,
    [string]$Match,
    [ValidateRange(1024,16777216)][int]$ScanBytes = 1048576,
    [string]$Config
)
$ErrorActionPreference = 'Stop'
$ExperimentRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ExperimentRoot '..\..\scripts\project_env.ps1')
if (-not $Config) { $Config = Join-Path $ExperimentRoot 'local_board.json' }
$board = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json
$sshAlias = if ($board.sshAlias) { $board.sshAlias } else { 'rk3588' }
$remoteRoot = if ($board.remoteRoot) { $board.remoteRoot } else { '~/orbslam3_cpu_baseline' }
if ($sshAlias -notmatch '^[A-Za-z0-9_.-]+$' -or $sshAlias.StartsWith('-')) { throw 'Invalid SSH alias' }
if ($remoteRoot -notmatch '^(~/|/)[A-Za-z0-9_./-]+$') { throw 'Invalid remoteRoot: use a Linux path without spaces' }
$sshOptions = @('-o','BatchMode=yes','-o','NumberOfPasswordPrompts=0','-o','ConnectTimeout=10')
if ($board.sshProxyCommand) {
    if ($board.sshProxyCommand -match '[\r\n]') {throw 'Invalid local SSH proxy command'}
    $sshOptions += @('-o',('ProxyCommand=' + $board.sshProxyCommand))
}
if ($Action -eq 'shell') {
    & ssh @sshOptions -t $sshAlias
    exit $LASTEXITCODE
}
if ($Action -in @('exec','start','status','wait','log') -and [string]::IsNullOrWhiteSpace($Value)) {
    throw "Action $Action requires a command or job ID"
}
$request = @{ action=$Action; value=$Value; name=$Name; seconds=$Seconds; lines=$Lines;
              max_chars=$MaxChars; match=$Match; scan_bytes=$ScanBytes }
$json = $request | ConvertTo-Json -Compress
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
$shellRoot = if ($remoteRoot.StartsWith('~/')) { '${HOME}/' + $remoteRoot.Substring(2) } else { $remoteRoot }
$remoteCommand = 'python3 "' + $shellRoot + '/scripts/remote_job.py" request ' + $encoded
& ssh @sshOptions $sshAlias $remoteCommand
exit $LASTEXITCODE
