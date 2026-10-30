param([ValidateSet('status','log')][string]$Action='status', [string]$JobId, [int]$Lines=12)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\scripts\project_env.ps1')
$taskExperimentRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskPcRoot = Join-Path $taskExperimentRoot 'runtime\pc'
if (-not $JobId) { $JobId = (Get-Content -LiteralPath (Join-Path $taskPcRoot 'latest_job.txt') -Raw).Trim() }
if ($JobId -notmatch '^PC0_[0-9T]+$') { throw 'Invalid PC0 job id' }
$taskJobRoot = Join-Path $taskPcRoot $JobId
$taskState = Get-Content -LiteralPath (Join-Path $taskJobRoot 'state.json') -Raw | ConvertFrom-Json
if ($Action -eq 'status') {
    $taskState | Select-Object job_id,status,phase,exit_code,error,
        @{Name='memory_test';Expression={$_.memory_acceptance.status}},
        @{Name='keep_awake';Expression={[bool]$_.windows_execution_request.active -and -not $_.windows_execution_request_released}},
        started_utc,finished_utc,formal_b3_started | ConvertTo-Json
} else {
    if ($Lines -lt 1 -or $Lines -gt 30) { throw 'Lines must be between 1 and 30' }
    $taskLog = Join-Path $taskJobRoot ($taskState.phase + '.log')
    if (Test-Path -LiteralPath $taskLog) {
        Get-Content -LiteralPath $taskLog -Tail $Lines | ForEach-Object {
            if ($_.Length -gt 400) { $_.Substring(0,400) + ' [truncated]' } else { $_ }
        }
    }
}
