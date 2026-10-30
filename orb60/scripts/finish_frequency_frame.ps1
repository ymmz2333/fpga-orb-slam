[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Job,[ValidateSet(2,4)][int]$Ppc=4,[string]$DescriptorProtocolReuse='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$freqFrameJob=[IO.Path]::GetFullPath($Job)
$freqFrameConfig=Get-Content -LiteralPath (Join-Path $freqFrameJob 'status.json') -Raw | ConvertFrom-Json
$freqFrameShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$freqFramePrefix="frame$Ppc"
$freqLayer=(Get-Content -LiteralPath (Join-Path $freqFrameJob "layer${Ppc}_hls_job.txt") -Raw).Trim()
$freqDescriptor=(Get-Content -LiteralPath (Join-Path $freqFrameJob 'descriptor_hls_job.txt') -Raw).Trim()
$freqFrameState=[ordered]@{State='RUNNING';Stage='RANDOM_AXI';ProcessId=$PID;LayerPpc=$Ppc;FrequencyMHz=125;StartedUtc=[DateTime]::UtcNow.ToString('o');Scope='Fresh125MHz RTL with DDR normalized to reference100MHz bytes/s and response-ns; route/board acceptance separate'}
function Save-FrequencyFrame {$freqFrameState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $freqFrameJob ($freqFramePrefix+'_status.json')) -Encoding UTF8}
Save-FrequencyFrame
try {
    $protocolArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'datapath_axi_gate.ps1'),'-LayerHlsJob',$freqLayer,'-DescriptorHlsJob',$freqDescriptor,'-JobFile',(Join-Path $freqFrameJob ($freqFramePrefix+'_protocol_job.txt')))
    if($DescriptorProtocolReuse) {$protocolArgs+=@('-DescriptorProtocolReuse',$DescriptorProtocolReuse)}
    & $freqFrameShell @protocolArgs *> (Join-Path $freqFrameJob ($freqFramePrefix+'_protocol.log'))
    if($LASTEXITCODE) {throw 'Fresh125MHz randomized AXI/reset/barrier failed'}
    $protocol=(Get-Content -LiteralPath (Join-Path $freqFrameJob ($freqFramePrefix+'_protocol_job.txt')) -Raw).Trim();$freqFrameState['ProtocolJob']=$protocol
    $freqFrameState.Stage='NATIVE_FRAME';Save-FrequencyFrame
    & $freqFrameShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'native_frame.ps1') -LayerHlsJob $freqLayer -DescriptorHlsJob $freqDescriptor -BenchmarkJob $freqFrameConfig.BenchmarkJob -ProtocolJob $protocol -JobFile (Join-Path $freqFrameJob ($freqFramePrefix+'_job.txt')) *> (Join-Path $freqFrameJob ($freqFramePrefix+'.log'))
    if($LASTEXITCODE) {throw 'Fresh125MHz normalized DDR native frame failed'}
    $frame=(Get-Content -LiteralPath (Join-Path $freqFrameJob ($freqFramePrefix+'_job.txt')) -Raw).Trim();$freqFrameState['FrameJob']=$frame
    & $ProjectPython (Join-Path $PSScriptRoot 'compare_native_architecture.py') --candidate $frame --baseline $freqFrameConfig.BaselineFrameJob --output (Join-Path $freqFrameJob ($freqFramePrefix+'_comparison')) *> (Join-Path $freqFrameJob ($freqFramePrefix+'_compare.log'))
    if($LASTEXITCODE) {throw 'Normalized DDR cross-frequency comparison failed'}
    $freqFrameState.State='SUCCEEDED';$freqFrameState.Stage='COMPLETE'
} catch {$freqFrameState.State='FAILED';$freqFrameState['Error']=$_.Exception.Message;throw}
finally {$freqFrameState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-FrequencyFrame}
