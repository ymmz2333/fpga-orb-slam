[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ArchitectureJob,
      [Parameter(Mandatory=$true)][string]$BaselineTimingJob,[string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$gatePrior=Get-Content -LiteralPath (Join-Path $ArchitectureJob 'status.json') -Raw | ConvertFrom-Json
if($gatePrior.State -ne 'SUCCEEDED' -or $gatePrior.Stage -ne 'HLS_GATES_COMPLETE' -or $gatePrior.FrequencyMHz -ne 100) {throw 'Architecture HLS acceptance is required'}
foreach($gatePair in @(@('layer2',$gatePrior.layer2HlsJob),@('descriptor',$gatePrior.descriptorHlsJob))) {
    $gateHls=Get-Content -LiteralPath (Join-Path $gatePair[1] 'status.json') -Raw | ConvertFrom-Json
    if($gateHls.State -ne 'SUCCEEDED' -or !$gateHls.Cosim -or $gateHls.Kernel -ne $gatePair[0] -or $gateHls.PeriodNs -ne 10) {throw 'Requires exact matching 100 MHz co-sim'}
    foreach($gateSource in (Get-Content -LiteralPath (Join-Path $gatePair[1] 'source_manifest.json') -Raw | ConvertFrom-Json)) {
        if((Get-FileHash -LiteralPath (Join-Path $gatePair[1] ('inputs/'+$gateSource.Path))).Hash -ne $gateSource.SHA256) {throw 'Frozen HLS source changed'}
    }
}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_architecture_protocol_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$gateJob=[IO.Path]::GetFullPath($Job)
if(Test-Path -LiteralPath (Join-Path $gateJob 'status.json')) {throw 'Refusing to reuse an existing protocol job'}
$gateInputs=Join-Path $gateJob 'inputs';New-Item -ItemType Directory -Path $gateInputs -Force | Out-Null
$gateTools=@()
foreach($gateFile in @('architecture_protocol.ps1','checkpoint_diagnostics.ps1','datapath_axi_gate.ps1','environment.ps1','summarize_diagnostics.py')) {
    $gateTool=Join-Path $PSScriptRoot $gateFile
    Copy-Item -LiteralPath $gateTool -Destination $gateInputs
    $gateTools+=@{Path=$gateTool;SHA256=(Get-FileHash -LiteralPath $gateTool).Hash}
}
$gateTools | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $gateJob 'tool_manifest.json') -Encoding UTF8
$gateState=[ordered]@{State='RUNNING';Stage='BASELINE_DIAGNOSTICS';Job=$gateJob;ProcessId=$PID;
    ArchitectureJob=[IO.Path]::GetFullPath($ArchitectureJob);Scope='Retained baseline diagnostics then candidate random AXI; shared DDR/frame/route pending';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-ProtocolState {$gateState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $gateJob 'status.json') -Encoding UTF8}
Save-ProtocolState
Write-Output "ORB60_ARCHITECTURE_PROTOCOL_JOB=$gateJob PID=$PID"
$gateShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
try {
    $gateFile=Join-Path $gateJob 'diagnostic_job.txt'
    & $gateShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'checkpoint_diagnostics.ps1') -TimingJob $BaselineTimingJob -JobFile $gateFile *> (Join-Path $gateJob 'diagnostics.log')
    if($LASTEXITCODE) {throw 'Baseline diagnostic gate failed; see diagnostics.log'}
    $gateState['DiagnosticJob']=(Get-Content -LiteralPath $gateFile -Raw).Trim()
    $gateState.Stage='RANDOM_AXI';Save-ProtocolState
    $gateFile=Join-Path $gateJob 'protocol_job.txt'
    & $gateShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'datapath_axi_gate.ps1') -LayerHlsJob $gatePrior.layer2HlsJob -DescriptorHlsJob $gatePrior.descriptorHlsJob -JobFile $gateFile *> (Join-Path $gateJob 'axi.log')
    if($LASTEXITCODE) {throw 'Candidate random AXI gate failed; see axi.log'}
    $gateState['ProtocolJob']=(Get-Content -LiteralPath $gateFile -Raw).Trim()
    foreach($gateTool in $gateTools) {if((Get-FileHash -LiteralPath $gateTool.Path).Hash -ne $gateTool.SHA256) {throw 'Gate tool changed while running'}}
    $gateState.State='SUCCEEDED';$gateState.Stage='DIAGNOSTICS_PROTOCOL_COMPLETE'
} catch {$gateState.State='FAILED';$gateState['Error']=$_.Exception.Message;throw}
finally {$gateState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-ProtocolState}
