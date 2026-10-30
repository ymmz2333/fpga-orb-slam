param(
    [string]$Command,
    [string]$Upload,
    [string]$Download,
    [string]$RemotePath,
    [string]$Config
)
$ErrorActionPreference = 'Stop'
$ExperimentRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ExperimentRoot '..\..\scripts\project_env.ps1')
if (-not $Config) { $Config = Join-Path $ExperimentRoot 'local_board.json' }
$board = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json
$sshOptions = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15')
if ($board.sshAlias) {
    $destination = $board.sshAlias
} else {
    $key = Join-Path $ProjectRoot $board.keyPath
    $sshOptions = @('-i', $key) + $sshOptions
    $destination = "$($board.user)@$($board.host)"
}
if ($Upload) {
    & scp @sshOptions $Upload "${destination}:$RemotePath"
} elseif ($Download) {
    & scp @sshOptions "${destination}:$RemotePath" $Download
} elseif ($Command) {
    & ssh @sshOptions $destination $Command
} else {
    throw 'Specify -Command, -Upload, or -Download.'
}
if ($LASTEXITCODE -ne 0) { throw "SSH/SCP exited with $LASTEXITCODE" }
