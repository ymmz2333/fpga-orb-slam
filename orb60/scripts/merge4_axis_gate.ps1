[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$HlsJob,[Parameter(Mandatory=$true)][string]$ProductionLayer,[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$mergeJob=Join-Path $Orb60Root ('build/optimized/gates/{0}_merge4_axis_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))
$mergeTests=Join-Path $mergeJob 'inputs/tests';New-Item -ItemType Directory -Path $mergeTests -Force | Out-Null
foreach($name in @('run_merge4_axis.py','test_merge4_axis.py','gpi_runtime.py')) {Copy-Item -LiteralPath (Join-Path $Orb60Root "tests/$name") -Destination $mergeTests}
$mergeState=[ordered]@{State='RUNNING';Stage='AXIS_RANDOM';Job=$mergeJob;HlsJob=$HlsJob;ProductionLayer=$ProductionLayer;ProcessId=$PID;StartedUtc=[DateTime]::UtcNow.ToString('o');Scope='Isolated production-source quad serializer random AXIS/reset only'}
if($JobFile) {$mergeJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
Write-Output "MERGE4_AXIS_JOB=$mergeJob PID=$PID"
function Save-Merge {$mergeState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $mergeJob 'status.json') -Encoding UTF8}
Save-Merge
try {
    & $ProjectPython (Join-Path $mergeTests 'run_merge4_axis.py') --hls $HlsJob --production $ProductionLayer --output $mergeJob 2>&1 | Tee-Object -FilePath (Join-Path $mergeJob 'axis.log')
    if($LASTEXITCODE) {throw 'Independent four-candidate AXIS/reset gate failed'}
    $mergeState.State='SUCCEEDED';$mergeState.Stage='COMPLETE'
} catch {$mergeState.State='FAILED';$mergeState['Error']=$_.Exception.Message;throw}
finally {$mergeState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-Merge}
