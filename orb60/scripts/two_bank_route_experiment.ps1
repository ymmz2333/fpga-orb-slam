[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BankingJob,
      [Parameter(Mandatory=$true)][string]$AcceptedDescriptor,[string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$routeProbeShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$routeProbePrior=Get-Content -LiteralPath (Join-Path $BankingJob 'status.json') -Raw | ConvertFrom-Json
$routeProbeProof=Get-Content -LiteralPath (Join-Path $BankingJob 'banking_comparison.json') -Raw | ConvertFrom-Json
if($routeProbePrior.State -ne 'SUCCEEDED' -or $routeProbePrior.Stage -ne 'HLS_BANKING_GATES_COMPLETE' -or !$routeProbeProof.banking_gate_pass) {throw 'Requires actual two-bank HLS/II and exact co-sim acceptance'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_two_bank_route_probe_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$routeProbeJob=[IO.Path]::GetFullPath($Job)
if(Test-Path -LiteralPath (Join-Path $routeProbeJob 'status.json')) {throw 'Refusing an existing route probe'}
$routeProbeLayer=Join-Path $routeProbeJob 'accepted_layer_hls'
New-Item -ItemType Directory -Path $routeProbeLayer -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $BankingJob 'comparison.json') -Destination $routeProbeLayer
@{State='SUCCEEDED';layer2Job=$routeProbePrior.LayerHlsJob;Scope='Exact HLS/II only; this carrier is not a protocol/frame acceptance'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $routeProbeLayer 'status.json') -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $Orb60Root 'docs/NEXT_OPTIMIZATION_PLAN_ZH.md') -Destination (Join-Path $routeProbeJob 'plan_snapshot.md')
$routeProbeState=[ordered]@{State='RUNNING';Stage='VIVADO_ROUTE';Job=$routeProbeJob;ProcessId=$PID;BankingJob=$BankingJob;
    Scope='Directional 100MHz full-route Slice/timing evidence after exact HLS co-sim; candidate random AXI/frame/release deferred per user';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-RouteProbeState {$routeProbeState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $routeProbeJob 'status.json') -Encoding UTF8}
Save-RouteProbeState;Write-Output "ORB60_TWO_BANK_ROUTE_PROBE_JOB=$routeProbeJob PID=$PID"
try {
    $routeProbeChildFile=Join-Path $routeProbeJob 'route_job.txt'
    & $routeProbeShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') -AcceptedLayer $routeProbeLayer -AcceptedDescriptor $AcceptedDescriptor -FrequencyMHz 100 -Jobs 4 -ExtendedDiagnostics -JobFile $routeProbeChildFile *> (Join-Path $routeProbeJob 'route.log')
    if($LASTEXITCODE) {throw 'Two-bank full-route experiment failed; original child evidence retained'}
    $routeProbeChild=(Get-Content -LiteralPath $routeProbeChildFile -Raw).Trim()
    $routeProbeResult=Get-Content -LiteralPath (Join-Path $routeProbeChild 'status.json') -Raw | ConvertFrom-Json
    if($routeProbeResult.State -ne 'SUCCEEDED') {throw 'Missing complete route/diagnostics acceptance'}
    $routeProbeState['RouteJob']=$routeProbeChild;$routeProbeState['Timing']=$routeProbeResult.Timing
    $routeProbeState.State='SUCCEEDED';$routeProbeState.Stage='ROUTE_PROBE_COMPLETE'
} catch {$routeProbeState.State='FAILED';$routeProbeState['Error']=$_.Exception.Message;throw}
finally {$routeProbeState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-RouteProbeState}
