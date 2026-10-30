[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PreviousFrontJob, [string]$ReuseFront2Job)
. (Join-Path $PSScriptRoot 'environment.ps1')
$previous=[IO.Path]::GetFullPath($PreviousFrontJob)
$previousState=Get-Content -LiteralPath (Join-Path $previous 'status.json') -Raw | ConvertFrom-Json
if ($previousState.State -ne 'SUCCEEDED' -or !$previousState.Cosim -or $previousState.Kernel -ne 'front' -or $previousState.PeriodNs -ne 10) {
    throw 'Comparison requires an accepted 10 ns front64 co-simulation job'
}
$name='{0}_front2_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/optimized/comparison/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='HOST';Job=$job;PreviousFrontJob=$previous;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_FRONT2_GATE_JOB=$job"
try {
    if ($ReuseFront2Job) {
        $child=Get-Item -LiteralPath ([IO.Path]::GetFullPath($ReuseFront2Job))
        $state['postcheckOnly']=$true
    } else {
        & (Join-Path $PSScriptRoot 'host.ps1') -Variant optimized *>&1 | Tee-Object -FilePath (Join-Path $job 'host.log')
        $state.Stage='HLS_FRONT2'
        $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
        & (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel front2 -Cosim *>&1 | Tee-Object -FilePath (Join-Path $job 'front2.log')
        $child=Get-ChildItem -LiteralPath (Join-Path $Orb60Root 'build/optimized/hls') -Directory -Filter '*_front2_*' | Sort-Object CreationTimeUtc -Descending | Select-Object -First 1
    }
    if (!$child) {throw 'Missing front2 HLS job'}
    $childState=Get-Content -LiteralPath (Join-Path $child.FullName 'status.json') -Raw | ConvertFrom-Json
    if ($childState.State -ne 'SUCCEEDED' -or $childState.Kernel -ne 'front2' -or !$childState.Cosim -or $childState.PeriodNs -ne 10 -or (!$ReuseFront2Job -and ([DateTime]$childState.StartedUtc -lt [DateTime]$state.StartedUtc))) {
        throw 'Incomplete or stale front2 HLS child'
    }
    $state['front2Job']=$child.FullName
    $state.Stage='COMPARE'
    $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compare_front2.py') -Destination $job
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compare_hls.py') -Destination $job
    & $ProjectPython (Join-Path $PSScriptRoot 'compare_front2.py') --previous $previous --front2 $child.FullName --output (Join-Path $job 'comparison.json')
    if ($LASTEXITCODE -ne 0) {throw '2PPC throughput post-check failed; inspect comparison.json'}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
