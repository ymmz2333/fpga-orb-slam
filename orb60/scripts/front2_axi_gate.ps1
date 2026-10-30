[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AcceptedComparison)
. (Join-Path $PSScriptRoot 'environment.ps1')
$accepted=[IO.Path]::GetFullPath($AcceptedComparison)
$prior=Get-Content -LiteralPath (Join-Path $accepted 'status.json') -Raw | ConvertFrom-Json
$proof=Get-Content -LiteralPath (Join-Path $accepted 'comparison.json') -Raw | ConvertFrom-Json
if ($prior.State -ne 'SUCCEEDED' -or !$proof.throughput_gate_pass) {throw 'Requires accepted front2 functional/throughput comparison'}
$hls=$prior.front2Job
$name='{0}_front2_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/optimized/gates/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='PYTHON_ORACLE';Job=$job;AcceptedComparison=$accepted;HlsJob=$hls;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_FRONT2_AXI_JOB=$job"
try {
    $vectors=Join-Path $job 'vectors'
    & $ProjectPython (Join-Path $Orb60Root 'tests/prepare.py') $hls $vectors --kernel front2
    if ($LASTEXITCODE -ne 0) {throw 'Independent Python/C++ front2 vector check failed'}
    foreach ($mode in @('smoke','full')) {
        $state.Stage="AXI_$($mode.ToUpper())"
        $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
        $runArgs=@((Join-Path $Orb60Root 'tests/run_axi.py'),'--hls-job',$hls,'--vectors',$vectors,'--kernel','front2','--output',(Join-Path $job $mode))
        if ($mode -eq 'smoke') {$runArgs += '--smoke'}
        $ErrorActionPreference='Continue'
        & $ProjectPython @runArgs 2>&1 | Tee-Object -FilePath (Join-Path $job "$mode.log")
        $code=$LASTEXITCODE
        $ErrorActionPreference='Stop'
        if ($code -ne 0) {throw "Front2 AXI $mode failed (exit $code)"}
    }
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
