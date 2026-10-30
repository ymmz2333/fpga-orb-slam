[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AcceptedComparison,[ValidateRange(1,16)][int]$Jobs=4)
. (Join-Path $PSScriptRoot 'environment.ps1')
$accepted=[IO.Path]::GetFullPath($AcceptedComparison)
$prior=Get-Content -LiteralPath (Join-Path $accepted 'status.json') -Raw | ConvertFrom-Json
$proof=Get-Content -LiteralPath (Join-Path $accepted 'comparison.json') -Raw | ConvertFrom-Json
if ($prior.State -ne 'SUCCEEDED' -or !$proof.throughput_gate_pass -or !$proof.axi_all_64) {throw 'Missing accepted shared-layer co-simulation/II/interface evidence'}
$hls=[IO.Path]::GetFullPath($prior.layer2Job)
$allowed=[IO.Path]::GetFullPath((Join-Path $Orb60Root 'build'))+'\'
if (!$hls.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)) {throw 'Layer HLS job must belong to orb60/build'}
$hlsState=Get-Content -LiteralPath (Join-Path $hls 'status.json') -Raw | ConvertFrom-Json
if ($hlsState.State -ne 'SUCCEEDED' -or !$hlsState.Cosim -or $hlsState.Kernel -ne 'layer2' -or $hlsState.PeriodNs -ne 10 -or $hlsState.Part -ne 'xc7z015clg485-2') {throw 'Unexpected layer HLS source acceptance/device/clock'}
$manifest=Get-Content -LiteralPath (Join-Path $hls 'source_manifest.json') -Raw | ConvertFrom-Json
foreach ($record in $manifest) {
    if ((Get-FileHash -LiteralPath (Join-Path (Join-Path $hls 'inputs') $record.Path)).Hash -ne $record.SHA256) {throw "Accepted input changed: $($record.Path)"}
}
$ip=Join-Path $hls 'projects/layer2/solution1/impl/ip'
$component=Get-Content -LiteralPath (Join-Path $ip 'component.xml') -Raw
if ($component -notmatch '<[^>]*name>fastv2_layer2_hls</[^>]*name>') {throw 'Wrong packaged IP'}
$id=[guid]::NewGuid().ToString('N').Substring(0,8)
$name='{0}_layer2_100mhz_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$id
$job=Join-Path $Orb60Root "build/optimized/timing/$name"
$scratch=Join-Path $VivadoBuildRoot "orb60/l$id"
if (Test-Path -LiteralPath $scratch) {throw 'Refusing existing layer scratch directory'}
$inputs=Join-Path $job 'inputs'
$liveInputs=Join-Path $scratch 'inputs'
New-Item -ItemType Directory -Path $inputs -Force | Out-Null
New-Item -ItemType Directory -Path $liveInputs -Force | Out-Null
foreach ($file in @('build_layer2_system.tcl','route_reports.tcl','timing_checks.tcl','ps_config.tcl')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$file") -Destination $inputs
    Copy-Item -LiteralPath (Join-Path $inputs $file) -Destination $liveInputs
}
Copy-Item -LiteralPath $ip -Destination (Join-Path $scratch 'ip') -Recurse
Copy-Item -LiteralPath (Join-Path $hls 'source_manifest.json') -Destination $inputs
$maxBytes=0
foreach ($file in Get-ChildItem -LiteralPath $ip -Recurse -File) {
    $relative=$file.FullName.Substring($ip.Length+1)
    $generated=Join-Path $scratch "vivado/p.gen/sources_1/bd/s/ip/s_layer_0/$relative"
    $bytes=[Text.Encoding]::UTF8.GetByteCount($generated)
    $maxBytes=[Math]::Max($maxBytes,$bytes)
    if ($bytes -ge 240) {throw "Generated layer path lacks Windows headroom: $generated"}
}
$hashes=Get-ChildItem -LiteralPath (Join-Path $scratch 'ip') -Recurse -File | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($scratch.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$hashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $inputs 'ip_manifest.json') -Encoding UTF8
$env:ORB60_LAYER_TIMING_ROOT=$scratch.Replace('\','/')
$env:ORB60_LAYER_TIMING_JOBS=$Jobs
$state=[ordered]@{State='RUNNING';Stage='VIVADO_ROUTE';Job=$job;ScratchRoot=$scratch;AcceptedComparison=$accepted;HlsJob=$hls;MaximumPredictedIpPathBytes=$maxBytes;Part='xc7z015clg485-2';FrequencyMHz=100;Scope='Shared-read layer routed timing/resource experiment; descriptors/protocol/board acceptance pending';PostRoutePhysOptApplied=$false;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_LAYER2_TIMING_JOB=$job"
Write-Output "ORB60_LAYER2_TIMING_SCRATCH=$scratch MAX_IP_PATH_BYTES=$maxBytes"
Push-Location $scratch
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $liveInputs 'build_layer2_system.tcl') -log (Join-Path $job 'vivado.log') -journal (Join-Path $job 'vivado.jou')
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if ($code -ne 0 -or !(Test-Path -LiteralPath (Join-Path $scratch 'vivado/.vivado_timing_success'))) {throw "Shared-layer routed gate failed (exit $code); measured violations are retained"}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {
    Pop-Location
    $reports=Join-Path $job 'reports'
    New-Item -ItemType Directory -Path $reports -Force | Out-Null
    $liveReports=Join-Path $scratch 'vivado'
    if (Test-Path -LiteralPath $liveReports) {
        foreach ($file in Get-ChildItem -LiteralPath $liveReports -Filter 'post_*' -File) {Copy-Item -LiteralPath $file.FullName -Destination $reports}
    }
    $metricFile=Join-Path $reports 'post_route_metrics.tsv'
    if (Test-Path -LiteralPath $metricFile) {
        $metrics=[ordered]@{}
        foreach ($line in Get-Content -LiteralPath $metricFile) {$fields=$line -split "`t",2; if ($fields.Count -eq 2) {$metrics[$fields[0]]=$fields[1]}}
        $state['Timing']=$metrics
    }
    $state['FinishedUtc']=[DateTime]::UtcNow.ToString('o')
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $status -Encoding UTF8
}
