[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$HlsJob,
      [Parameter(Mandatory=$true)][string]$Vectors,
      [ValidateRange(1,16)][int]$Jobs=4)
. (Join-Path $PSScriptRoot 'environment.ps1')
$hls=[IO.Path]::GetFullPath($HlsJob)
$hlsState=Get-Content -LiteralPath (Join-Path $hls 'status.json') -Raw | ConvertFrom-Json
if ($hlsState.Variant -ne 'baseline' -or $hlsState.State -ne 'SUCCEEDED') { throw 'Requires a completed baseline HLS job' }
$name='{0}_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/baseline/gates/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='AXI_SMOKE';Job=$job;HlsJob=$hls;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_BASELINE_GATE_JOB=$job"
try {
    foreach ($mode in @('smoke','full')) {
        $state.Stage="AXI_$($mode.ToUpper())"
        $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
        $args=@((Join-Path $Orb60Root 'tests/run_axi.py'),'--hls-job',$hls,'--vectors',[IO.Path]::GetFullPath($Vectors),'--output',(Join-Path $job $mode))
        if ($mode -eq 'smoke') {$args += '--smoke'}
        $ErrorActionPreference='Continue'
        & $ProjectPython @args 2>&1 | Tee-Object -FilePath (Join-Path $job "$mode.log")
        $code=$LASTEXITCODE
        $ErrorActionPreference='Stop'
        if ($code -ne 0) {throw "AXI $mode gate failed (exit $code)"}
    }
    $state.Stage='VIVADO_ROUTE'
    $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    & (Join-Path $PSScriptRoot 'board.ps1') -HlsJob $hls -Jobs $Jobs
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
