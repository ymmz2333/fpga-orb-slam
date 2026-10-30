[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AcceptedLayer,
      [Parameter(Mandatory=$true)][string]$AcceptedDescriptor,
      [Parameter(Mandatory=$true)][string]$NativeJob,
      [ValidateRange(1,16)][int]$Jobs=4)
. (Join-Path $PSScriptRoot 'environment.ps1')
$freqLayer=[IO.Path]::GetFullPath($AcceptedLayer)
$freqDesc=[IO.Path]::GetFullPath($AcceptedDescriptor)
$freqNative=[IO.Path]::GetFullPath($NativeJob)
$freqLayerState=Get-Content -LiteralPath (Join-Path $freqLayer 'status.json') -Raw | ConvertFrom-Json
$freqDescState=Get-Content -LiteralPath (Join-Path $freqDesc 'status.json') -Raw | ConvertFrom-Json
$freqNativeState=Get-Content -LiteralPath (Join-Path $freqNative 'status.json') -Raw | ConvertFrom-Json
$freqLayerProof=Get-Content -LiteralPath (Join-Path $freqLayer 'comparison.json') -Raw | ConvertFrom-Json
$freqDescProof=Get-Content -LiteralPath (Join-Path $freqDesc 'comparison.json') -Raw | ConvertFrom-Json
if($freqLayerState.State -ne 'SUCCEEDED' -or !$freqLayerProof.throughput_gate_pass -or
   $freqDescState.State -ne 'SUCCEEDED' -or !$freqDescProof.pipeline_gate_pass -or $freqNativeState.State -ne 'SUCCEEDED') {
    throw 'Requires the retained 100 MHz exact/II/whole-frame gates'
}
$freqOrigins=@{layer2=[IO.Path]::GetFullPath($freqLayerState.layer2Job);descriptor=[IO.Path]::GetFullPath($freqDescState.DescriptorHlsJob)}
foreach($entry in (Get-Content -LiteralPath (Join-Path $freqNative 'rtl_manifest.json') -Raw | ConvertFrom-Json)) {
    $freqPath=Join-Path $freqOrigins[$entry.kernel] "projects/$($entry.kernel)/solution1/syn/verilog/$($entry.name)"
    if((Get-FileHash -LiteralPath $freqPath).Hash.ToLowerInvariant() -ne $entry.sha256) {throw 'Native gate is not paired with retained RTL'}
}
$freqName='{0}_frequency125_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$freqJob=Join-Path $Orb60Root "build/optimized/comparison/$freqName"
$freqInputs=Join-Path $freqJob 'inputs';New-Item -ItemType Directory -Path $freqInputs -Force | Out-Null
$freqTools=@('frequency_gate.ps1','hls.ps1','hls.tcl','orb_timing.ps1','compare_layer2.py','compare_descriptor.py','compare_hls.py','environment.ps1')
$freqFiles=@{}
foreach($name in $freqTools) {
    $source=Join-Path $PSScriptRoot $name;Copy-Item -LiteralPath $source -Destination $freqInputs
    $freqFiles[$source]=(Get-FileHash -LiteralPath $source).Hash
}
foreach($name in @('build_orb_system.tcl','route_reports.tcl','timing_checks.tcl','ps_config.tcl')) {
    $source=Join-Path $Orb60Root "vivado/$name";Copy-Item -LiteralPath $source -Destination $freqInputs
    $freqFiles[$source]=(Get-FileHash -LiteralPath $source).Hash
}
$freqFiles | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $freqJob 'tool_manifest.json') -Encoding UTF8
$freqState=[ordered]@{State='RUNNING';Stage='HLS_LAYER2_8NS';ProcessId=$PID;Job=$freqJob;FrequencyMHz=125;
    SourceLayer=$freqOrigins.layer2;SourceDescriptor=$freqOrigins.descriptor;Native100MHz=$freqNative;
    Scope='Bounded 8 ns HLS rebuild + complete 125 MHz route; candidate random-AXI/frame/board release not yet accepted';
    StartedUtc=[DateTime]::UtcNow.ToString('o')}
$freqStatus=Join-Path $freqJob 'status.json'
function Save-FrequencyState {$freqState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $freqStatus -Encoding UTF8}
function Check-FrequencyTools {
    foreach($source in $freqFiles.Keys) {if((Get-FileHash -LiteralPath $source).Hash -ne $freqFiles[$source]) {throw "Tool changed during bounded experiment: $source"}}
}
Save-FrequencyState
Write-Output "ORB60_FREQUENCY_JOB=$freqJob PID=$PID"
try {
    foreach($kernel in @('layer2','descriptor')) {
        Check-FrequencyTools
        $freqState.Stage="HLS_${kernel}_8NS";Save-FrequencyState
        $freqChildFile=Join-Path $freqJob "${kernel}_job.txt"
        $freqArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'hls.ps1'),
            '-Variant','optimized','-Kernel',$kernel,'-Period','8','-Cosim','-SourceJob',$freqOrigins[$kernel],'-JobFile',$freqChildFile)
        if($kernel -eq 'descriptor') {$freqArgs+=@('-DescriptorVectors',(Join-Path $freqOrigins.descriptor 'descriptor_vectors'))}
        $ErrorActionPreference='Continue'
        & powershell.exe @freqArgs *> (Join-Path $freqJob "${kernel}_hls.log")
        $freqChildExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
        if($freqChildExit) {throw "8 ns $kernel HLS failed; see ${kernel}_hls.log"}
        $freqChild=(Get-Content -LiteralPath $freqChildFile -Raw).Trim()
        $childState=Get-Content -LiteralPath (Join-Path $freqChild 'status.json') -Raw | ConvertFrom-Json
        if($childState.State -ne 'SUCCEEDED' -or !$childState.Cosim -or $childState.PeriodNs -ne 8 -or $childState.Kernel -ne $kernel) {throw 'Missing 8 ns child acceptance'}
        $oldHashes=Get-Content -LiteralPath (Join-Path $freqOrigins[$kernel] 'source_manifest.json') -Raw | ConvertFrom-Json
        $newHashes=Get-Content -LiteralPath (Join-Path $freqChild 'source_manifest.json') -Raw | ConvertFrom-Json
        if($oldHashes.Count -ne $newHashes.Count) {throw 'Clock comparison source set differs'}
        foreach($entry in $oldHashes) {
            $match=@($newHashes | Where-Object Path -EQ $entry.Path)
            if($match.Count -ne 1 -or $match[0].SHA256 -ne $entry.SHA256) {throw 'Clock comparison source bytes differ'}
        }
        $freqCandidate=Join-Path $freqJob "accepted_$kernel";New-Item -ItemType Directory -Path $freqCandidate | Out-Null
        $freqCompareArgs=@('--job',$freqChild,'--output',(Join-Path $freqCandidate 'comparison.json'))
        if($kernel -eq 'layer2') {$freqCompareArgs+=@('--front2',$freqLayerProof.standalone_front2.job)}
        $ErrorActionPreference='Continue'
        & $ProjectPython (Join-Path $freqInputs "compare_$kernel.py") @freqCompareArgs *> (Join-Path $freqJob "${kernel}_compare.log")
        $freqCompareExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
        if($freqCompareExit) {throw "8 ns $kernel II/interface gate failed"}
        $freqCandidateState=[ordered]@{State='SUCCEEDED';PeriodNs=8;FrequencyMHz=125;Scope='C/RTL exact + actual II/interface only; random AXI/native/route pending'}
        if($kernel -eq 'layer2') {$freqCandidateState['layer2Job']=$freqChild}
        else {$freqCandidateState['DescriptorHlsJob']=$freqChild}
        $freqCandidateState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $freqCandidate 'status.json') -Encoding UTF8
        $freqState["${kernel}HlsJob"]=$freqChild;Save-FrequencyState
        Write-Output "ORB60_FREQUENCY_HLS_PASS kernel=$kernel job=$freqChild"
    }
    Check-FrequencyTools
    $freqState.Stage='ROUTE_125MHZ';Save-FrequencyState
    $freqRouteFile=Join-Path $freqJob 'route_job.txt'
    $ErrorActionPreference='Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') `
        -AcceptedLayer (Join-Path $freqJob 'accepted_layer2') -AcceptedDescriptor (Join-Path $freqJob 'accepted_descriptor') `
        -FrequencyMHz 125 -Jobs $Jobs -JobFile $freqRouteFile *> (Join-Path $freqJob 'route.log')
    $freqRouteExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
    if(Test-Path -LiteralPath $freqRouteFile) {$freqState['RouteJob']=(Get-Content -LiteralPath $freqRouteFile -Raw).Trim();Save-FrequencyState}
    if($freqRouteExit) {throw '125 MHz routed gate failed; actual timing/resources remain in the child reports'}
    $routeState=Get-Content -LiteralPath (Join-Path $freqState.RouteJob 'status.json') -Raw | ConvertFrom-Json
    if($routeState.State -ne 'SUCCEEDED' -or $routeState.FrequencyMHz -ne 125) {throw 'Missing 125 MHz route acceptance'}
    Check-FrequencyTools
    $freqState.State='SUCCEEDED';$freqState.Stage='COMPLETE';$freqState['Timing']=$routeState.Timing
} catch {$freqState.State='FAILED';$freqState['Error']=$_.Exception.Message;throw}
finally {$freqState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-FrequencyState}
