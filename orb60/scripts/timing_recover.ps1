[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$TimingJob)
. (Join-Path $PSScriptRoot 'environment.ps1')
$parent=[IO.Path]::GetFullPath($TimingJob)
$prior=Get-Content -LiteralPath (Join-Path $parent 'status.json') -Raw | ConvertFrom-Json
if ($prior.Part -ne 'xc7z015clg485-2' -or $prior.FrequencyMHz -ne 100) {throw 'Unexpected parent device/clock'}
$kind='front2'
$frontTop='fastv2_front2_hls'
$reportScope='complete three-core routed top; protocol/board acceptance pending'
if ($prior.HlsJob) {
    $origin=Get-Content -LiteralPath (Join-Path $prior.HlsJob 'status.json') -Raw | ConvertFrom-Json
    if ($origin.Kernel -eq 'layer2') {
        if ($origin.State -ne 'SUCCEEDED' -or !$origin.Cosim) {throw 'Shared-layer source acceptance missing'}
        $kind='layer2';$frontTop='fastv2_layer2_hls'
        $reportScope='shared-reader 2PPC layer routed top; protocol/descriptor/board acceptance pending'
    }
}
$runDir=Join-Path $prior.ScratchRoot 'vivado/p.runs/impl_1'
$checkpoint=Join-Path $runDir 's_wrapper_routed.dcp'
if (!(Test-Path -LiteralPath (Join-Path $runDir '.route_design.end.rst')) -or (Test-Path -LiteralPath (Join-Path $runDir '.route_design.error.rst')) -or !(Test-Path -LiteralPath $checkpoint)) {throw 'Missing completed routed checkpoint; no report recovery permitted'}
$id=[guid]::NewGuid().ToString('N').Substring(0,8)
$name='{0}_{1}_recovery_{2}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$kind,$id
$job=Join-Path $Orb60Root "build/optimized/timing/$name"
$scratch=Join-Path $VivadoBuildRoot "orb60/r$id"
$inputs=Join-Path $scratch 'inputs'
if (Test-Path -LiteralPath $scratch) {throw 'Refusing to reuse a recovery scratch directory'}
New-Item -ItemType Directory -Path $inputs -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $job 'inputs') -Force | Out-Null
foreach ($file in @('recover_reports.tcl','route_reports.tcl','timing_checks.tcl')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$file") -Destination $inputs
    Copy-Item -LiteralPath (Join-Path $inputs $file) -Destination (Join-Path $job 'inputs')
}
$reports=Join-Path $scratch 'reports'
$env:ORB60_ROUTED_CHECKPOINT=$checkpoint.Replace('\','/')
$env:ORB60_RECOVER_REPORTS=$reports.Replace('\','/')
$env:ORB60_ORIGINAL_TIMING_REPORT=(Join-Path $runDir 's_wrapper_timing_summary_routed.rpt').Replace('\','/')
$env:ORB60_RECOVER_FRONT_TOP=$frontTop
$env:ORB60_RECOVER_SCOPE=$reportScope
$state=[ordered]@{State='RUNNING';Stage='ROUTED_REPORTS';Job=$job;ParentTimingJob=$parent;ScratchRoot=$scratch;Checkpoint=$checkpoint;CheckpointSHA256=(Get-FileHash -LiteralPath $checkpoint).Hash;PostRoutePhysOptApplied=$false;Scope=$reportScope;CoreTop=$frontTop;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$status=Join-Path $job 'status.json'
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $status -Encoding UTF8
Write-Output "ORB60_TIMING_RECOVERY_JOB=$job"
Push-Location $scratch
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $inputs 'recover_reports.tcl') -log (Join-Path $job 'vivado.log') -journal (Join-Path $job 'vivado.jou')
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if ($code -ne 0 -or !(Test-Path -LiteralPath (Join-Path $reports '.vivado_timing_success'))) {throw "Routed report recovery failed (exit $code); inspect retained evidence"}
    $state.State='SUCCEEDED';$state.Stage='COMPLETE'
} catch {$state.State='FAILED';$state['Error']=$_.Exception.Message;throw}
finally {
    Pop-Location
    $archive=Join-Path $job 'reports'
    New-Item -ItemType Directory -Path $archive -Force | Out-Null
    if (Test-Path -LiteralPath $reports) {
        foreach ($file in Get-ChildItem -LiteralPath $reports -File) {Copy-Item -LiteralPath $file.FullName -Destination $archive}
    }
    $metricFile=Join-Path $archive 'post_route_metrics.tsv'
    if (Test-Path -LiteralPath $metricFile) {
        $metrics=[ordered]@{}
        foreach ($line in Get-Content -LiteralPath $metricFile) {$fields=$line -split "`t",2; if ($fields.Count -eq 2) {$metrics[$fields[0]]=$fields[1]}}
        $state['Timing']=$metrics
    }
    $state['FinishedUtc']=[DateTime]::UtcNow.ToString('o')
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $status -Encoding UTF8
}
