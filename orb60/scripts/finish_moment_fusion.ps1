[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ProbeJob,
      [Parameter(Mandatory=$true)][string]$BaselineDescriptor,
      [Parameter(Mandatory=$true)][string]$AcceptedLayer,
      [Parameter(Mandatory=$true)][string]$LayerProtocol,
      [Parameter(Mandatory=$true)][string]$BenchmarkJob,
      [Parameter(Mandatory=$true)][string]$BaselineFrame,
      [string]$Job='',[ValidateRange(1,16)][int]$Jobs=4)
. (Join-Path $PSScriptRoot 'environment.ps1')
$fusionProbe=[IO.Path]::GetFullPath($ProbeJob)
$fusionConfig=Get-Content -LiteralPath (Join-Path $fusionProbe 'status.json') -Raw | ConvertFrom-Json
if($fusionConfig.State -ne 'SUCCEEDED' -or $fusionConfig.Cosim -or !$fusionConfig.NoExport -or
   $fusionConfig.DescriptorMomentFusion -ne 1 -or $fusionConfig.PeriodNs -ne 8) {throw 'Requires accepted automatic-mapping8ns fused receiver probe'}
$fusionLayerConfig=Get-Content -LiteralPath (Join-Path $AcceptedLayer 'status.json') -Raw | ConvertFrom-Json
$fusionLayerHls=[IO.Path]::GetFullPath($fusionLayerConfig.layer2Job)
if($fusionLayerConfig.State -ne 'SUCCEEDED') {throw 'Layer carrier is not accepted'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_fusion_accept_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$fusionAccept=[IO.Path]::GetFullPath($Job);New-Item -ItemType Directory -Path $fusionAccept -Force | Out-Null
$fusionTools=Join-Path $fusionAccept 'inputs_tools';New-Item -ItemType Directory -Path $fusionTools -Force | Out-Null
foreach($file in @('finish_moment_fusion.ps1','compare_moment_fusion.py','compare_descriptor.py','compare_hls.py','hls.ps1','hls.tcl',
    'datapath_axi_gate.ps1','native_frame.ps1','compare_native_architecture.py','orb_timing.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $fusionTools
}
$fusionToolHashes=Get-ChildItem -LiteralPath $fusionTools -File | ForEach-Object {[ordered]@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}}
$fusionToolHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $fusionAccept 'tool_manifest.json') -Encoding UTF8
$fusionState=[ordered]@{State='RUNNING';Stage='HLS_COSIM_EXPORT';Job=$fusionAccept;ProcessId=$PID;ProbeJob=$fusionProbe;
    BaselineDescriptor=$BaselineDescriptor;LayerHlsJob=$fusionLayerHls;AcceptedLayer=$AcceptedLayer;LayerProtocol=$LayerProtocol;
    BenchmarkJob=$BenchmarkJob;BaselineFrame=$BaselineFrame;FrequencyMHz=125;StartedUtc=[DateTime]::UtcNow.ToString('o');
    Scope='Fresh fused descriptor C/RTL, protocol, shared-DDR frame and complete route; unchanged accepted4PPC layer reused by hashes; no bit/PS/board claim'}
function Save-FusionAcceptance {$fusionState | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $fusionAccept 'status.json') -Encoding UTF8}
function Check-FusionTools {
    foreach($file in $fusionToolHashes) {
        if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $file.Path)).Hash -ne $file.SHA256) {throw ('Live tool changed during frozen acceptance: '+$file.Path)}
    }
}
$fusionShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
Save-FusionAcceptance;Write-Output "ORB60_FUSION_ACCEPT_JOB=$fusionAccept PID=$PID"
try {
    Check-FusionTools
    & $fusionShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -Period 8 -Cosim -SourceProbe $fusionProbe -DescriptorWidthMode 2 -DescriptorPrefetch 8 -DescriptorPatch32 -DescriptorMomentFusion 1 -DescriptorVectors (Join-Path $BaselineDescriptor 'descriptor_vectors') -JobFile (Join-Path $fusionAccept 'descriptor_hls_job.txt') *> (Join-Path $fusionAccept 'hls.log')
    if($LASTEXITCODE) {throw 'Fresh fused descriptor C/RTL/IP failed'}
    $fusionHls=(Get-Content -LiteralPath (Join-Path $fusionAccept 'descriptor_hls_job.txt') -Raw).Trim();$fusionState['DescriptorHlsJob']=$fusionHls
    $fusionState.Stage='ARCHITECTURE_AND_MMIO';Save-FusionAcceptance
    $fusionCarrier=Join-Path $fusionAccept 'accepted_descriptor';New-Item -ItemType Directory -Path $fusionCarrier -Force | Out-Null
    & $ProjectPython (Join-Path $fusionTools 'compare_descriptor.py') --job $fusionHls --output (Join-Path $fusionCarrier 'comparison.json') *> (Join-Path $fusionAccept 'descriptor_compare.log')
    if($LASTEXITCODE) {throw 'Fused descriptor actual II/AXI gate failed'}
    & $ProjectPython (Join-Path $fusionTools 'compare_moment_fusion.py') --baseline $BaselineDescriptor --jobs $fusionHls --output (Join-Path $fusionAccept 'fusion_hls_comparison.json') *> (Join-Path $fusionAccept 'fusion_compare.log')
    if($LASTEXITCODE) {throw 'Fused descriptor source/architecture/adapter/MMIO check failed'}
    [ordered]@{State='SUCCEEDED';DescriptorHlsJob=$fusionHls;PeriodNs=8;FrequencyMHz=125;DescriptorMomentFusion=1;Scope='Fresh exact C/RTL and II/interface gates; protocol/frame/route separate'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $fusionCarrier 'status.json') -Encoding UTF8
    $fusionState.Stage='RANDOM_AXI';Save-FusionAcceptance;Check-FusionTools
    & $fusionShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'datapath_axi_gate.ps1') -LayerHlsJob $fusionLayerHls -DescriptorHlsJob $fusionHls -LayerProtocolReuse $LayerProtocol -JobFile (Join-Path $fusionAccept 'protocol_job.txt') *> (Join-Path $fusionAccept 'protocol.log')
    if($LASTEXITCODE) {throw 'Fresh fused descriptor random AXI/reset/error/barrier failed'}
    $fusionProtocol=(Get-Content -LiteralPath (Join-Path $fusionAccept 'protocol_job.txt') -Raw).Trim();$fusionState['ProtocolJob']=$fusionProtocol
    $fusionState.Stage='NATIVE_FRAME';Save-FusionAcceptance;Check-FusionTools
    & $fusionShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'native_frame.ps1') -LayerHlsJob $fusionLayerHls -DescriptorHlsJob $fusionHls -BenchmarkJob $BenchmarkJob -ProtocolJob $fusionProtocol -JobFile (Join-Path $fusionAccept 'frame_job.txt') *> (Join-Path $fusionAccept 'frame.log')
    if($LASTEXITCODE) {throw 'Fused descriptor shared-DDR exact native frame failed'}
    $fusionFrame=(Get-Content -LiteralPath (Join-Path $fusionAccept 'frame_job.txt') -Raw).Trim();$fusionState['FrameJob']=$fusionFrame
    & $ProjectPython (Join-Path $fusionTools 'compare_native_architecture.py') --candidate $fusionFrame --baseline $BaselineFrame --output (Join-Path $fusionAccept 'frame_comparison') *> (Join-Path $fusionAccept 'frame_compare.log')
    if($LASTEXITCODE) {throw 'Fused frame service/bytes comparison failed'}
    $fusionState.Stage='COMPLETE_TOP_ROUTE';Save-FusionAcceptance;Check-FusionTools
    & $fusionShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') -AcceptedLayer $AcceptedLayer -AcceptedDescriptor $fusionCarrier -FrequencyMHz 125 -Jobs $Jobs -ExtendedDiagnostics -FrameJob $fusionFrame -JobFile (Join-Path $fusionAccept 'route_job.txt') *> (Join-Path $fusionAccept 'route.log')
    if(Test-Path -LiteralPath (Join-Path $fusionAccept 'route_job.txt')) {$fusionState['RouteJob']=(Get-Content -LiteralPath (Join-Path $fusionAccept 'route_job.txt') -Raw).Trim();Save-FusionAcceptance}
    if($LASTEXITCODE) {throw 'Fused complete routed top failed; retain actual result'}
    $fusionState.State='SUCCEEDED';$fusionState.Stage='COMPUTER_GATES_COMPLETE'
} catch {$fusionState.State='FAILED';$fusionState['Error']=$_.Exception.Message;throw}
finally {$fusionState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-FusionAcceptance}
