[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AcceptedLayer,[Parameter(Mandatory=$true)][string]$AcceptedDescriptor,
      [ValidateRange(125,200)][double]$FrequencyMHz=150,[ValidateSet('none','light','full')][string]$ControlSlices='light',[ValidateRange(1,16)][int]$Jobs=4,[string]$JobFile='',
      [string]$FrameJob='',[switch]$ExtendedDiagnostics)
. (Join-Path $PSScriptRoot 'environment.ps1')
$orbLayerAccepted=[IO.Path]::GetFullPath($AcceptedLayer)
$orbDescAccepted=[IO.Path]::GetFullPath($AcceptedDescriptor)
$orbLayerPrior=Get-Content -LiteralPath (Join-Path $orbLayerAccepted 'status.json') -Raw | ConvertFrom-Json
$orbDescPrior=Get-Content -LiteralPath (Join-Path $orbDescAccepted 'status.json') -Raw | ConvertFrom-Json
$orbLayerProof=Get-Content -LiteralPath (Join-Path $orbLayerAccepted 'comparison.json') -Raw | ConvertFrom-Json
$orbDescProof=Get-Content -LiteralPath (Join-Path $orbDescAccepted 'comparison.json') -Raw | ConvertFrom-Json
if($orbLayerPrior.State -ne 'SUCCEEDED' -or !$orbLayerProof.throughput_gate_pass -or !$orbLayerProof.axi_all_64 -or
   $orbDescPrior.State -ne 'SUCCEEDED' -or !$orbDescProof.pipeline_gate_pass -or !$orbDescProof.axi_all_64) {throw 'Missing accepted exact RTL/II/AXI gates'}
$orbOrigins=@{layer=[IO.Path]::GetFullPath($orbLayerPrior.layer2Job);desc=[IO.Path]::GetFullPath($orbDescPrior.DescriptorHlsJob)}
$orbAllowed=[IO.Path]::GetFullPath((Join-Path $Orb60Root 'build'))+'\'
$orbIpPaths=@{}
$orbPpc=2
foreach($orbCoreName in @('layer','desc')) {
    $orbHlsPath=$orbOrigins[$orbCoreName]
    if(!$orbHlsPath.StartsWith($orbAllowed,[StringComparison]::OrdinalIgnoreCase)) {throw 'HLS source must belong to orb60/build'}
    $orbHlsState=Get-Content -LiteralPath (Join-Path $orbHlsPath 'status.json') -Raw | ConvertFrom-Json
    $orbKernel=if($orbCoreName -eq 'layer') {'layer2'} else {'descriptor'}
    if($orbCoreName -eq 'layer') {$orbPpc=if($null -ne $orbHlsState.LayerPpc) {[int]$orbHlsState.LayerPpc} else {2};if($orbPpc -notin @(2,4)) {throw 'Unsupported PPC'}}
    if($orbHlsState.State -ne 'SUCCEEDED' -or !$orbHlsState.Cosim -or $orbHlsState.Kernel -ne $orbKernel -or
       [Math]::Abs([double]$orbHlsState.PeriodNs-1000.0/$FrequencyMHz) -gt 0.000001 -or
       $orbHlsState.Part -ne 'xc7z015clg485-2') {throw 'Wrong source acceptance/device/clock'}
    foreach($orbRecord in (Get-Content -LiteralPath (Join-Path $orbHlsPath 'source_manifest.json') -Raw | ConvertFrom-Json)) {
        if((Get-FileHash -LiteralPath (Join-Path $orbHlsPath ('inputs/'+$orbRecord.Path))).Hash -ne $orbRecord.SHA256) {throw 'Accepted source changed'}
    }
    $orbIpPaths[$orbCoreName]=Join-Path $orbHlsPath "projects/$orbKernel/solution1/impl/ip"
}
if($FrameJob) {
    $orbFrameState=Get-Content -LiteralPath (Join-Path $FrameJob 'status.json') -Raw | ConvertFrom-Json
    $orbFramePerformance=Get-Content -LiteralPath (Join-Path $FrameJob 'performance.json') -Raw | ConvertFrom-Json
    if($orbFrameState.State -ne 'SUCCEEDED' -or $orbFrameState.Stage -ne 'COMPLETE' -or
       $orbFramePerformance.status -ne 'PASS' -or !$orbFramePerformance.rtl_unchanged -or
       [int]$orbFramePerformance.clock_period_ps -ne [int][Math]::Round(1000000.0/$FrequencyMHz) -or $orbFramePerformance.runs.Count -ne 4) {throw 'Matching complete four-profile native frame acceptance is required'}
    foreach($orbFrameRtl in (Get-Content -LiteralPath (Join-Path $FrameJob 'rtl_manifest.json') -Raw | ConvertFrom-Json)) {
        $orbSourceKey=if($orbFrameRtl.kernel -eq 'layer2') {'layer'} elseif($orbFrameRtl.kernel -eq 'descriptor') {'desc'} else {throw 'Unknown frame RTL kernel'}
        $orbSourceRtl=Join-Path $orbOrigins[$orbSourceKey] "projects/$($orbFrameRtl.kernel)/solution1/syn/verilog/$($orbFrameRtl.name)"
        if((Get-FileHash -LiteralPath $orbSourceRtl).Hash.ToLowerInvariant() -ne $orbFrameRtl.sha256) {throw 'Frame gate used different RTL'}
    }
}
$orbId=[guid]::NewGuid().ToString('N').Substring(0,8)
$orbJob=Join-Path $Orb60Root ('build/optimized/timing/{0}_orb_{1}mhz_{2}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$FrequencyMHz,$orbId)
$orbScratch=Join-Path $VivadoBuildRoot "orb60/i$orbId"
if(Test-Path -LiteralPath $orbScratch) {throw 'Refusing existing integrated scratch'}
$orbInputs=Join-Path $orbJob 'inputs';$orbLiveInputs=Join-Path $orbScratch 'inputs'
New-Item -ItemType Directory -Path $orbInputs,$orbLiveInputs -Force | Out-Null
foreach($orbFile in @('build_orb_frequency.tcl','route_reports.tcl','timing_checks.tcl','ps_config.tcl')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "vivado/$orbFile") -Destination $orbInputs
    Copy-Item -LiteralPath (Join-Path $orbInputs $orbFile) -Destination $orbLiveInputs
}
if($ExtendedDiagnostics) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root 'vivado/diagnostic_reports.tcl') -Destination $orbInputs
    Copy-Item -LiteralPath (Join-Path $orbInputs 'diagnostic_reports.tcl') -Destination $orbLiveInputs
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'summarize_diagnostics.py') -Destination $orbInputs
}
New-Item -ItemType Directory -Path (Join-Path $orbScratch 'ip') | Out-Null
$orbMaxPathBytes=0
foreach($orbCoreName in @('layer','desc')) {
    $orbIp=$orbIpPaths[$orbCoreName]
    Copy-Item -LiteralPath $orbIp -Destination (Join-Path $orbScratch "ip/$orbCoreName") -Recurse
    Copy-Item -LiteralPath (Join-Path $orbOrigins[$orbCoreName] 'source_manifest.json') -Destination (Join-Path $orbInputs "${orbCoreName}_source_manifest.json")
    foreach($orbFile in Get-ChildItem -LiteralPath $orbIp -Recurse -File) {
        $orbRelative=$orbFile.FullName.Substring($orbIp.Length+1)
        $orbGenerated=Join-Path $orbScratch "vivado/p.gen/sources_1/bd/s/ip/s_${orbCoreName}_0/$orbRelative"
        $orbBytes=[Text.Encoding]::UTF8.GetByteCount($orbGenerated)
        $orbMaxPathBytes=[Math]::Max($orbMaxPathBytes,$orbBytes)
        if($orbBytes -ge 240) {throw "Integrated generated path lacks headroom: $orbGenerated"}
    }
}
$orbHashes=Get-ChildItem -LiteralPath (Join-Path $orbScratch 'ip') -Recurse -File | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($orbScratch.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$orbHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $orbInputs 'ip_manifest.json') -Encoding UTF8
$env:ORB60_ORB_TIMING_ROOT=$orbScratch.Replace('\','/');$env:ORB60_ORB_TIMING_JOBS=$Jobs
$env:ORB60_ORB_TIMING_FREQUENCY=$FrequencyMHz.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
$env:ORB60_CONTROL_SLICE_MODE=@{none=0;light=7;full=1}[$ControlSlices]
$env:ORB60_ORB_TIMING_PPC=$orbPpc
$env:ORB60_ROUTE_DIAGNOSTICS=if($ExtendedDiagnostics) {'1'} else {'0'}
$orbState=[ordered]@{State='RUNNING';Stage='VIVADO_ROUTE';Job=$orbJob;ScratchRoot=$orbScratch;AcceptedLayer=$orbLayerAccepted;AcceptedDescriptor=$orbDescAccepted;LayerHlsJob=$orbOrigins.layer;DescriptorHlsJob=$orbOrigins.desc;MaximumPredictedIpPathBytes=$orbMaxPathBytes;Part='xc7z015clg485-2';FrequencyMHz=$FrequencyMHz;Scope='Complete 2PPC layer + exact A32 descriptor routed timing/resource; candidate joint DDR/protocol/PS/board gates pending';PostRoutePhysOptApplied=$false;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID}
$orbStatus=Join-Path $orbJob 'status.json'
$orbState['ClockSource']='AMD Clocking Wizard MMCM from100MHz PS FCLK';$orbState['ControlSlices']=$ControlSlices;
$orbState['FrameJob']=$FrameJob;$orbState['ExtendedDiagnostics']=[bool]$ExtendedDiagnostics;$orbState['LayerPpc']=$orbPpc
$orbState.Scope="Complete ${orbPpc}PPC layer + exact A32 descriptor routed timing/resource; candidate joint DDR/protocol/PS/board gates pending"
if($FrameJob) {$orbState.Scope="Complete ${orbPpc}PPC layer + exact A32 descriptor routed timing/resource; exact matching native frame gate passed, PS/board pending"}
$orbToolManifest=Get-ChildItem -LiteralPath $orbInputs -File | ForEach-Object {
    [ordered]@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$orbToolManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $orbJob 'tool_manifest.json') -Encoding UTF8
$orbState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $orbStatus -Encoding UTF8
if($JobFile) {$orbJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
Write-Output "ORB60_ORB_TIMING_JOB=$orbJob"
Write-Output "ORB60_ORB_TIMING_PID=$PID SCRATCH=$orbScratch MAX_IP_PATH_BYTES=$orbMaxPathBytes"
Push-Location $orbScratch
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -source (Join-Path $orbLiveInputs 'build_orb_frequency.tcl') -log (Join-Path $orbJob 'vivado.log') -journal (Join-Path $orbJob 'vivado.jou')
    $orbCode=$LASTEXITCODE;$ErrorActionPreference='Stop'
    if($orbCode -ne 0 -or !(Test-Path -LiteralPath (Join-Path $orbScratch 'vivado/.vivado_timing_success'))) {throw "Integrated routed gate failed (exit $orbCode); measured results retained"}
    if($ExtendedDiagnostics) {
        & $ProjectPython (Join-Path $orbInputs 'summarize_diagnostics.py') (Join-Path $orbScratch 'vivado/post_route_diagnostics')
        if($LASTEXITCODE) {throw 'Missing or inconsistent extended route diagnostics'}
    }
    $orbState.State='SUCCEEDED';$orbState.Stage='COMPLETE'
} catch {$orbState.State='FAILED';$orbState['Error']=$_.Exception.Message;throw}
finally {
    Pop-Location
    $orbArchive=Join-Path $orbJob 'reports';New-Item -ItemType Directory -Path $orbArchive -Force | Out-Null
    if(Test-Path -LiteralPath (Join-Path $orbScratch 'vivado')) {
        foreach($orbFile in Get-ChildItem -LiteralPath (Join-Path $orbScratch 'vivado') -Filter 'post_*' -File) {Copy-Item -LiteralPath $orbFile.FullName -Destination $orbArchive}
        if(Test-Path -LiteralPath (Join-Path $orbScratch 'vivado/post_route_diagnostics')) {
            Copy-Item -LiteralPath (Join-Path $orbScratch 'vivado/post_route_diagnostics') -Destination $orbArchive -Recurse
        }
    }
    $orbMetricFile=Join-Path $orbArchive 'post_route_metrics.tsv'
    if(Test-Path -LiteralPath $orbMetricFile) {
        $orbMetrics=[ordered]@{}
        foreach($orbLine in Get-Content -LiteralPath $orbMetricFile) {$orbFields=$orbLine -split "`t",2;if($orbFields.Count -eq 2){$orbMetrics[$orbFields[0]]=$orbFields[1]}}
        $orbState['Timing']=$orbMetrics
    }
    $orbState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');$orbState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $orbStatus -Encoding UTF8
}
