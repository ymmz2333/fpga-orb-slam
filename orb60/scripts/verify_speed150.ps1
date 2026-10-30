[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$verifyOrb=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$verifyArtifact=Join-Path $verifyOrb 'artifacts/speed_joint_150mhz'
$verifyEvidence=Join-Path $verifyOrb 'evidence/speed_joint_150mhz'
$verifyManifest=Get-Content (Join-Path $verifyArtifact 'artifact_manifest.json') -Raw|ConvertFrom-Json
$verifyRelease=Get-Content (Join-Path $verifyArtifact 'release_validation.json') -Raw|ConvertFrom-Json
$verifyJoint=Get-Content (Join-Path $verifyEvidence 'joint_result.json') -Raw|ConvertFrom-Json
$verifyRoute=Get-Content (Join-Path $verifyEvidence 'route/status.json') -Raw|ConvertFrom-Json
if($verifyManifest.status -ne 'PASS' -or $verifyManifest.part -ne 'xc7z015clg485-2' -or $verifyManifest.frequency_mhz -ne 150 -or $verifyManifest.layer_ppc -ne 4 -or $verifyManifest.ps_fclk_input_mhz -ne 100) {throw 'Missing exact150MHz release configuration'}
if($verifyRelease.status -ne 'PASS' -or $verifyJoint.status -ne 'PASS' -or $verifyRoute.State -ne 'SUCCEEDED') {throw 'Missing complete joint/route acceptance'}
if($verifyManifest.physical_board_verified -or $verifyManifest.ps_modified) {throw 'Unsupported PS/board claim'}
if((Get-FileHash (Join-Path $verifyArtifact 'orb60_150mhz.bit')).Hash.ToLowerInvariant() -ne $verifyManifest.bit_sha256) {throw '150MHz bit hash mismatch'}
foreach($metric in @('tns_ns','ths_ns','tpws_ns','setup_failed_endpoints','hold_failed_endpoints','pulse_failed_endpoints')) {
    if([double]$verifyRoute.Timing.$metric -ne 0) {throw "Failed timing metric: $metric"}
}
if([double]$verifyRoute.Timing.wns_ns -lt 0 -or [double]$verifyRoute.Timing.whs_ns -lt 0) {throw 'Setup/hold violation'}
foreach($kernel in @('layer2','descriptor')) {
    $verifyFrozen=Join-Path $verifyOrb "frozen/speed_joint_150mhz/$kernel"
    $verifySource=Get-Content (Join-Path $verifyFrozen 'source_manifest.json') -Raw|ConvertFrom-Json
    foreach($entry in $verifySource) {
        if((Get-FileHash (Join-Path $verifyFrozen "inputs/$($entry.Path)")).Hash -ne $entry.SHA256) {throw "Frozen source hash mismatch: $kernel/$($entry.Path)"}
    }
    $verifyHls=Get-Content (Join-Path $verifyFrozen 'status.json') -Raw|ConvertFrom-Json
    if($verifyHls.State -ne 'SUCCEEDED' -or !$verifyHls.Cosim -or $verifyHls.NoExport -or [Math]::Abs([double]$verifyHls.PeriodNs-1000.0/150) -gt 1e-9) {throw 'Frozen HLS clock/C-RTL mismatch'}
}
$verifyPerformance=Get-Content (Join-Path $verifyEvidence 'board_4gb/performance.json') -Raw|ConvertFrom-Json
if($verifyPerformance.status -ne 'PASS' -or !$verifyPerformance.rtl_unchanged -or !$verifyPerformance.legacy_replay_exact) {throw 'Missing exact shared-DDR evidence'}
$verifyPrimary=@($verifyPerformance.runs|Where-Object {$_.random_stall_percent -eq 0 -and ($_.read_initial_delay_ns -join ',') -eq '0,50'})
if($verifyPrimary.Count -ne 1 -or $verifyPrimary[0].ddr_capacity_bytes_per_second -ne 4000000000 -or ($verifyPrimary[0].frames.selected -join ',') -ne '280,942,0') {throw 'Sufficient-bandwidth profile mismatch'}
if(($verifyPrimary[0].frames.milliseconds|Measure-Object -Maximum).Maximum -gt 16.67) {throw 'Sufficient-bandwidth speed gate failed'}
Write-Output 'SPEED150_PACKAGE_PASS source/bit/route/exact-frame; PS and board remain pending'
