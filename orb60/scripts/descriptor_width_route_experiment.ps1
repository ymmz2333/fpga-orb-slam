[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WidthProbeDescriptor,
      [Parameter(Mandatory=$true)][string]$AcceptedLayer,[string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$widthRouteShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$widthRoutePrior=Get-Content -LiteralPath (Join-Path $WidthProbeDescriptor 'status.json') -Raw | ConvertFrom-Json
if($widthRoutePrior.State -ne 'SUCCEEDED' -or $widthRoutePrior.Cosim -or !$widthRoutePrior.NoExport -or $widthRoutePrior.DescriptorWidthMode -ne 2) {throw 'Requires successful bounded width2 synthesis probe'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_descriptor_width2_route_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$widthRouteJob=[IO.Path]::GetFullPath($Job)
if(Test-Path -LiteralPath (Join-Path $widthRouteJob 'status.json')) {throw 'Refusing an existing width route experiment'}
$widthRouteInputs=Join-Path $widthRouteJob 'inputs';New-Item -ItemType Directory -Path $widthRouteInputs -Force | Out-Null
foreach($name in @('descriptor_width_route_experiment.ps1','hls.ps1','hls.tcl','compare_descriptor.py','compare_hls.py','compare_descriptor_width_probes.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $widthRouteInputs
}
Copy-Item -LiteralPath (Join-Path $Orb60Root 'docs/NEXT_OPTIMIZATION_PLAN_ZH.md') -Destination (Join-Path $widthRouteInputs 'plan_snapshot.md')
$widthRouteTools=Get-ChildItem -LiteralPath $widthRouteInputs -File | ForEach-Object {@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}}
$widthRouteTools | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $widthRouteJob 'tool_manifest.json') -Encoding UTF8
$widthRouteState=[ordered]@{State='RUNNING';Stage='HLS_COSIM_WIDTH2';Job=$widthRouteJob;ProcessId=$PID;SourceProbe=$WidthProbeDescriptor;AcceptedLayer=$AcceptedLayer;
    Scope='Selected width2 exact frozen probe regenerated for co-sim/IP and directional100MHz complete route; candidate protocol/frame/release pending';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-WidthRouteState {$widthRouteState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $widthRouteJob 'status.json') -Encoding UTF8}
Save-WidthRouteState;Write-Output "ORB60_DESCRIPTOR_WIDTH_ROUTE_JOB=$widthRouteJob PID=$PID"
try {
    $childFile=Join-Path $widthRouteJob 'hls_job.txt'
    & $widthRouteShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -Period 10 -SourceProbe $WidthProbeDescriptor -DescriptorWidthMode 2 -DescriptorVectors (Join-Path $WidthProbeDescriptor 'descriptor_vectors') -Cosim -JobFile $childFile *> (Join-Path $widthRouteJob 'hls.log')
    if($LASTEXITCODE) {throw 'Width2 exact RTL/IP regeneration failed'}
    $child=(Get-Content -LiteralPath $childFile -Raw).Trim();$widthRouteState['DescriptorHlsJob']=$child;Save-WidthRouteState
    $accepted=Join-Path $widthRouteJob 'accepted_descriptor';New-Item -ItemType Directory -Path $accepted | Out-Null
    & $ProjectPython (Join-Path $widthRouteInputs 'compare_descriptor.py') --job $child --output (Join-Path $accepted 'comparison.json') *> (Join-Path $widthRouteJob 'compare.log')
    if($LASTEXITCODE) {throw 'Width2 real-II/interface post-check failed'}
    @{State='SUCCEEDED';DescriptorHlsJob=$child;Scope='Exact co-sim/II/64-bit only; candidate protocol/frame pending'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $accepted 'status.json') -Encoding UTF8
    $widthRouteState.Stage='VIVADO_ROUTE';Save-WidthRouteState
    $routeFile=Join-Path $widthRouteJob 'route_job.txt'
    & $widthRouteShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') -AcceptedLayer $AcceptedLayer -AcceptedDescriptor $accepted -FrequencyMHz 100 -Jobs 4 -ExtendedDiagnostics -JobFile $routeFile *> (Join-Path $widthRouteJob 'route.log')
    if($LASTEXITCODE) {throw 'Width2 directional complete route failed; original results retained'}
    $route=(Get-Content -LiteralPath $routeFile -Raw).Trim()
    $result=Get-Content -LiteralPath (Join-Path $route 'status.json') -Raw | ConvertFrom-Json
    if($result.State -ne 'SUCCEEDED') {throw 'Missing full routed acceptance'}
    $widthRouteState['RouteJob']=$route;$widthRouteState['Timing']=$result.Timing
    $widthRouteState.State='SUCCEEDED';$widthRouteState.Stage='WIDTH2_ROUTE_PROBE_COMPLETE'
} catch {$widthRouteState.State='FAILED';$widthRouteState['Error']=$_.Exception.Message;throw}
finally {$widthRouteState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-WidthRouteState}
