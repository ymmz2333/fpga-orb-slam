[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$TimingJob,
      [ValidateRange(1,16)][int]$Jobs=4,
      [ValidateSet('AggressiveExplore','Explore')][string]$Directive='AggressiveExplore')
. (Join-Path $PSScriptRoot 'environment.ps1')
$physicalParent=[IO.Path]::GetFullPath($TimingJob)
$physicalAllowed=[IO.Path]::GetFullPath((Join-Path $Orb60Root 'build'))+'\'
if(!$physicalParent.StartsWith($physicalAllowed,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Physical optimization parent must belong to orb60/build'
}
$physicalPrior=Get-Content -LiteralPath (Join-Path $physicalParent 'status.json') -Raw | ConvertFrom-Json
if($physicalPrior.State -ne 'FAILED' -or $physicalPrior.Part -ne 'xc7z015clg485-2' -or
   $physicalPrior.FrequencyMHz -ne 125 -or !$physicalPrior.Timing -or
   [double]$physicalPrior.Timing.setup_REQUIREMENT -ne 8 -or
   [double]$physicalPrior.Timing.wns_ns -ge 0) {
    throw 'Expected completed 125 MHz routed timing failure with actual 8 ns evidence'
}
foreach($physicalOrigin in @($physicalPrior.LayerHlsJob,$physicalPrior.DescriptorHlsJob)) {
    $physicalHls=Get-Content -LiteralPath (Join-Path $physicalOrigin 'status.json') -Raw | ConvertFrom-Json
    if($physicalHls.State -ne 'SUCCEEDED' -or !$physicalHls.Cosim -or $physicalHls.PeriodNs -ne 8) {
        throw 'Physical optimization requires accepted fresh 8 ns HLS kernels'
    }
}
$physicalScratchParent=[IO.Path]::GetFullPath($physicalPrior.ScratchRoot)
$physicalScratchAllowed=[IO.Path]::GetFullPath((Join-Path $VivadoBuildRoot 'orb60'))+'\'
if(!$physicalScratchParent.StartsWith($physicalScratchAllowed,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Checkpoint must belong to configured ORB60 Vivado scratch'
}
$physicalPassCount=1
if($physicalPrior.PostRoutePhysOptApplied) {
    $physicalPassCount=2
    if($physicalPrior.PhysicalPassCount) {$physicalPassCount=[int]$physicalPrior.PhysicalPassCount+1}
    if($physicalPassCount -gt 2) {throw 'The bounded experiment permits at most two physical passes'}
    $physicalCheckpoint=Join-Path $physicalScratchParent 'reports/next_system_routed.dcp'
    $physicalArchivedCheckpoint=Join-Path $physicalParent 'reports/next_system_routed.dcp'
    if(!$physicalPrior.Optimization -or !($physicalPrior.Optimization.PSObject.Properties.Name -contains 'after_wns_ns') -or
       !(Test-Path -LiteralPath $physicalCheckpoint) -or !(Test-Path -LiteralPath $physicalArchivedCheckpoint) -or
       (Get-FileHash -LiteralPath $physicalCheckpoint).Hash -ne (Get-FileHash -LiteralPath $physicalArchivedCheckpoint).Hash) {
        throw 'Missing completed physical optimization checkpoint or archive hash agreement'
    }
} else {
    $physicalRun=Join-Path $physicalScratchParent 'vivado/p.runs/impl_1'
    $physicalCheckpoint=Join-Path $physicalScratchParent 'vivado/next_system_routed.dcp'
    if(!(Test-Path -LiteralPath (Join-Path $physicalRun '.route_design.end.rst')) -or
       (Test-Path -LiteralPath (Join-Path $physicalRun '.route_design.error.rst')) -or
       !(Test-Path -LiteralPath $physicalCheckpoint)) {
        throw 'Missing completed fully routed parent checkpoint'
    }
}
$physicalId=[guid]::NewGuid().ToString('N').Substring(0,8)
$physicalJob=Join-Path $Orb60Root ('build/optimized/timing/{0}_physopt_125mhz_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$physicalId)
$physicalScratch=Join-Path $VivadoBuildRoot "orb60/x$physicalId"
if(Test-Path -LiteralPath $physicalScratch) {throw 'Refusing existing physical optimization scratch'}
$physicalInputs=Join-Path $physicalJob 'inputs'
$physicalLiveInputs=Join-Path $physicalScratch 'inputs'
New-Item -ItemType Directory -Path $physicalInputs,$physicalLiveInputs -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/post_route_physopt.tcl') -Destination $physicalInputs
foreach($physicalFile in @('route_reports.tcl','timing_checks.tcl')) {
    Copy-Item -LiteralPath (Join-Path $physicalParent "inputs/$physicalFile") -Destination $physicalInputs
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'post_route_physopt.ps1') -Destination $physicalInputs
foreach($physicalFile in Get-ChildItem -LiteralPath $physicalInputs -Filter '*.tcl' -File) {
    Copy-Item -LiteralPath $physicalFile.FullName -Destination $physicalLiveInputs
}
$physicalHashes=@(Get-ChildItem -LiteralPath $physicalInputs -File | ForEach-Object {
    [ordered]@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
})
$physicalHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $physicalInputs 'manifest.json') -Encoding UTF8
$physicalReports=Join-Path $physicalScratch 'reports'
$physicalHash=(Get-FileHash -LiteralPath $physicalCheckpoint).Hash
$env:ORB60_PHYSOPT_CHECKPOINT=$physicalCheckpoint.Replace('\','/')
$env:ORB60_PHYSOPT_REPORTS=$physicalReports.Replace('\','/')
$env:ORB60_PHYSOPT_PARENT_WNS=$physicalPrior.Timing.wns_ns
$env:ORB60_PHYSOPT_THREADS=$Jobs
$env:ORB60_PHYSOPT_DIRECTIVE=$Directive
$physicalState=[ordered]@{State='RUNNING';Stage='POST_ROUTE_PHYSOPT';Job=$physicalJob;ParentTimingJob=$physicalParent;ScratchRoot=$physicalScratch;Checkpoint=$physicalCheckpoint;CheckpointSHA256=$physicalHash;Part='xc7z015clg485-2';FrequencyMHz=125;Directive=$Directive;PhysicalPassCount=$physicalPassCount;PostRoutePhysOptRequested=$true;PostRoutePhysOptApplied=$false;ParentTiming=$physicalPrior.Timing;LayerHlsJob=$physicalPrior.LayerHlsJob;DescriptorHlsJob=$physicalPrior.DescriptorHlsJob;Scope='Bounded complete-top physical optimization; unchanged 8 ns HLS sources and clocks; candidate protocol/frame/PS/board gates pending';StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$physicalStatus=Join-Path $physicalJob 'status.json'
$physicalState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $physicalStatus -Encoding UTF8
Write-Output "ORB60_PHYSOPT_JOB=$physicalJob PID=$PID"
Push-Location $physicalScratch
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $physicalLiveInputs 'post_route_physopt.tcl') -log (Join-Path $physicalJob 'vivado.log') -journal (Join-Path $physicalJob 'vivado.jou') *> (Join-Path $physicalJob 'tool.log')
    $physicalCode=$LASTEXITCODE; $ErrorActionPreference='Stop'
    if($physicalCode -ne 0 -or !(Test-Path -LiteralPath (Join-Path $physicalReports '.vivado_timing_success'))) {
        throw "Physical optimization routed gate failed (exit $physicalCode); inspect actual retained timing"
    }
    $physicalState.State='SUCCEEDED';$physicalState.Stage='COMPLETE'
} catch {
    $physicalState.State='FAILED';$physicalState['Error']=$_.Exception.Message
    throw
} finally {
    Pop-Location
    if((Get-FileHash -LiteralPath $physicalCheckpoint).Hash -ne $physicalHash) {
        $physicalState.State='FAILED';$physicalState['Error']='Parent routed checkpoint changed'
    }
    $physicalArchive=Join-Path $physicalJob 'reports'
    New-Item -ItemType Directory -Path $physicalArchive -Force | Out-Null
    if(Test-Path -LiteralPath $physicalReports) {
        foreach($physicalFile in Get-ChildItem -LiteralPath $physicalReports -File) {
            Copy-Item -LiteralPath $physicalFile.FullName -Destination $physicalArchive
        }
    }
    $physicalOptimizationFile=Join-Path $physicalArchive 'physical_optimization.tsv'
    if(Test-Path -LiteralPath $physicalOptimizationFile) {
        $physicalProgress=[ordered]@{}
        foreach($physicalLine in Get-Content -LiteralPath $physicalOptimizationFile) {
            $physicalFields=$physicalLine -split "`t",2
            if($physicalFields.Count -eq 2) {$physicalProgress[$physicalFields[0]]=$physicalFields[1]}
        }
        $physicalState['Optimization']=$physicalProgress
        $physicalState.PostRoutePhysOptApplied=$physicalProgress.Contains('after_wns_ns')
    }
    $physicalMetricFile=Join-Path $physicalArchive 'post_route_metrics.tsv'
    if(Test-Path -LiteralPath $physicalMetricFile) {
        $physicalMetrics=[ordered]@{}
        foreach($physicalLine in Get-Content -LiteralPath $physicalMetricFile) {
            $physicalFields=$physicalLine -split "`t",2
            if($physicalFields.Count -eq 2) {$physicalMetrics[$physicalFields[0]]=$physicalFields[1]}
        }
        $physicalState['Timing']=$physicalMetrics
    }
    $physicalState['FinishedUtc']=[DateTime]::UtcNow.ToString('o')
    $physicalState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $physicalStatus -Encoding UTF8
}
if($physicalState.State -ne 'SUCCEEDED') {throw $physicalState.Error}
