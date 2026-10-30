[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PreviousFront2Job)
. (Join-Path $PSScriptRoot 'environment.ps1')
$previous=[IO.Path]::GetFullPath($PreviousFront2Job)
$prior=Get-Content -LiteralPath (Join-Path $previous 'status.json') -Raw | ConvertFrom-Json
if ($prior.State -ne 'SUCCEEDED' -or !$prior.Cosim -or $prior.Kernel -ne 'front2' -or $prior.PeriodNs -ne 10) {throw 'Requires accepted 100 MHz standalone front2 job'}
$name='{0}_layer2_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$job=Join-Path $Orb60Root "build/optimized/comparison/$name"
New-Item -ItemType Directory -Path $job | Out-Null
$state=[ordered]@{State='RUNNING';Stage='HOST';Job=$job;PreviousFront2Job=$previous;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_LAYER2_GATE_JOB=$job"
try {
    & (Join-Path $PSScriptRoot 'host.ps1') -Variant optimized *>&1 | Tee-Object -FilePath (Join-Path $job 'host.log')
    $state.Stage='HLS_LAYER2'
    $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    & (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel layer2 -Cosim *>&1 | Tee-Object -FilePath (Join-Path $job 'layer2.log')
    $child=Get-ChildItem -LiteralPath (Join-Path $Orb60Root 'build/optimized/hls') -Directory -Filter '*_layer2_*' | Sort-Object CreationTimeUtc -Descending | Select-Object -First 1
    if (!$child) {throw 'Missing layer2 HLS job'}
    $childState=Get-Content -LiteralPath (Join-Path $child.FullName 'status.json') -Raw | ConvertFrom-Json
    if ($childState.State -ne 'SUCCEEDED' -or !$childState.Cosim -or $childState.Kernel -ne 'layer2' -or ([DateTime]$childState.StartedUtc -lt [DateTime]$state.StartedUtc)) {throw 'Incomplete or stale layer2 job'}
    $state['layer2Job']=$child.FullName; $state.Stage='COMPARE'
    $state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compare_layer2.py') -Destination $job
    & $ProjectPython (Join-Path $PSScriptRoot 'compare_layer2.py') --job $child.FullName --front2 $previous --output (Join-Path $job 'comparison.json')
    if ($LASTEXITCODE -ne 0) {throw 'Shared-layer actual-II/interface post-check failed'}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {$state['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$state | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8}
