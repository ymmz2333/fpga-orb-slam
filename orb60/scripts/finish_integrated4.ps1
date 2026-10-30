[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Job,[ValidateSet('Route','Frame')][string]$Mode)
. (Join-Path $PSScriptRoot 'environment.ps1')
$integratedShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$integratedJob=[IO.Path]::GetFullPath($Job)
$integratedRootState=Get-Content -LiteralPath (Join-Path $integratedJob 'status.json') -Raw | ConvertFrom-Json
$integratedFrequency=if($integratedRootState.FrequencyMHz) {[int]$integratedRootState.FrequencyMHz} else {100}
if($integratedFrequency -notin @(100,125)) {throw 'Unsupported integrated clock'}
if($integratedRootState.Stage -ne 'JOINT_VERIFY' -or $integratedRootState.LayerPpc -ne 4) {throw 'Requires integrated4 accepted exact HLS/II pair'}
$integratedLayer=(Get-Content -LiteralPath (Join-Path $integratedJob 'layer_hls_job.txt') -Raw).Trim()
$integratedDescriptor=(Get-Content -LiteralPath (Join-Path $integratedJob 'descriptor_hls_job.txt') -Raw).Trim()
$integratedModeState=[ordered]@{State='RUNNING';Stage=$Mode;Job=$integratedJob;Mode=$Mode;ProcessId=$PID;StartedUtc=[DateTime]::UtcNow.ToString('o');Scope='Integrated4 candidate verification; no bitstream/PS/board acceptance'}
$integratedModeStatus=Join-Path $integratedJob ($Mode.ToLowerInvariant()+'_status.json')
function Save-IntegratedMode {$integratedModeState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $integratedModeStatus -Encoding UTF8}
Save-IntegratedMode;Write-Output "INTEGRATED4_${Mode}_PID=$PID JOB=$integratedJob"
try {
    if($Mode -eq 'Route') {
        & $integratedShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'orb_timing.ps1') -AcceptedLayer (Join-Path $integratedJob 'accepted_layer') -AcceptedDescriptor (Join-Path $integratedJob 'accepted_descriptor') -FrequencyMHz $integratedFrequency -Jobs 4 -ExtendedDiagnostics -JobFile (Join-Path $integratedJob 'route_job.txt') *> (Join-Path $integratedJob 'route.log')
        if($LASTEXITCODE) {throw 'Integrated4 full route failed; retain original child reports'}
        $child=(Get-Content -LiteralPath (Join-Path $integratedJob 'route_job.txt') -Raw).Trim()
        $proof=Get-Content -LiteralPath (Join-Path $child 'status.json') -Raw | ConvertFrom-Json
        if($proof.State -ne 'SUCCEEDED' -or $proof.LayerPpc -ne 4) {throw 'Missing complete4PPC routed acceptance'}
        $integratedModeState['RouteJob']=$child;$integratedModeState['Timing']=$proof.Timing
    } else {
        $integratedModeState.Stage='RANDOM_AXI';Save-IntegratedMode
        $protocolArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'datapath_axi_gate.ps1'),'-LayerHlsJob',$integratedLayer,'-DescriptorHlsJob',$integratedDescriptor,'-JobFile',(Join-Path $integratedJob 'protocol_job.txt'))
        if($integratedRootState.PreviousIntegratedJob) {
            $previousFrame=Get-Content -LiteralPath (Join-Path $integratedRootState.PreviousIntegratedJob 'frame_status.json') -Raw | ConvertFrom-Json
            $protocolArgs+=@('-DescriptorProtocolReuse',$previousFrame.ProtocolJob)
        }
        & $integratedShell @protocolArgs *> (Join-Path $integratedJob 'protocol.log')
        if($LASTEXITCODE) {throw 'Integrated4 randomized AXI/reset/barrier failed'}
        $protocol=(Get-Content -LiteralPath (Join-Path $integratedJob 'protocol_job.txt') -Raw).Trim();$integratedModeState['ProtocolJob']=$protocol
        $integratedModeState.Stage='NATIVE_FRAME';Save-IntegratedMode
        & $integratedShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'native_frame.ps1') -LayerHlsJob $integratedLayer -DescriptorHlsJob $integratedDescriptor -BenchmarkJob $integratedRootState.BenchmarkJob -ProtocolJob $protocol -JobFile (Join-Path $integratedJob 'frame_job.txt') *> (Join-Path $integratedJob 'frame.log')
        if($LASTEXITCODE) {throw 'Integrated4 native shared-DDR frame verification failed'}
        $frame=(Get-Content -LiteralPath (Join-Path $integratedJob 'frame_job.txt') -Raw).Trim();$integratedModeState['FrameJob']=$frame
        $integratedModeState.Stage='COMPARE';Save-IntegratedMode
        & $ProjectPython (Join-Path $integratedJob 'inputs/compare_native_architecture.py') --candidate $frame --baseline $integratedRootState.BaselineFrameJob --output (Join-Path $integratedJob 'frame_comparison') *> (Join-Path $integratedJob 'frame_compare.log')
        if($LASTEXITCODE) {throw 'Integrated4 same-DDR comparison failed'}
    }
    $integratedModeState.State='SUCCEEDED';$integratedModeState.Stage='COMPLETE'
} catch {$integratedModeState.State='FAILED';$integratedModeState['Error']=$_.Exception.Message;throw}
finally {$integratedModeState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-IntegratedMode}
