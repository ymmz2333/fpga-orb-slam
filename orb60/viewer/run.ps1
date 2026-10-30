param(
    [string]$Connect = '',
    [string]$Recording = '',
    [string]$Video = '',
    [string]$FrameMap = '',
    [string]$Config = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../scripts/project_env.ps1')
$viewerArgs = @((Join-Path $PSScriptRoot 'app.py'))
if ($Connect) { $viewerArgs += @('--connect', $Connect) }
if ($Recording) { $viewerArgs += @('--recording', $Recording) }
if ($Video) { $viewerArgs += @('--video', $Video) }
if ($FrameMap) { $viewerArgs += @('--frame-map', $FrameMap) }
if ($Config) { $viewerArgs += @('--config', $Config) }
& $ProjectPython @viewerArgs
exit $LASTEXITCODE
