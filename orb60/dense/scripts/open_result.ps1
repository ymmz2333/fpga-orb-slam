param([string]$Result,[string]$Video,[double]$ExitAfter = 0,[string]$Screenshot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
if (-not $Result) {
    $latest = Get-Content -Raw (Join-Path $ProjectRoot 'orb60/build/dense/latest.local.json') | ConvertFrom-Json
    $Result = Join-Path $ProjectRoot $latest.result
    $videoSetting = $latest.PSObject.Properties['video']
    if (-not $Video -and $videoSetting -and $videoSetting.Value) { $Video = Join-Path $ProjectRoot $videoSetting.Value }
}
if (-not (Test-Path -LiteralPath $Result)) { throw "建模结果不存在：$Result" }
$viewerArgs = @((Join-Path $ProjectRoot 'orb60/viewer/app.py'), '--dense', $Result)
if ($Video) { $viewerArgs += @('--video', $Video) }
if ($ExitAfter -gt 0) { $viewerArgs += @('--exit-after', $ExitAfter.ToString([cultureinfo]::InvariantCulture)) }
if ($Screenshot) { $viewerArgs += @('--screenshot', $Screenshot) }
& $ProjectPython @viewerArgs
exit $LASTEXITCODE
