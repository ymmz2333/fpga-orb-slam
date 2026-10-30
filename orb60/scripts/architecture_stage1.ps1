[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineLayer,
      [Parameter(Mandatory=$true)][string]$BaselineDescriptor,
      [Parameter(Mandatory=$true)][string]$Front2Hls,
      [Parameter(Mandatory=$true)][string]$DescriptorVectors,
      [string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$archShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
foreach($pair in @(@('layer2',$BaselineLayer),@('descriptor',$BaselineDescriptor),@('front2',$Front2Hls))) {
    $archPrior=Get-Content -LiteralPath (Join-Path $pair[1] 'status.json') -Raw | ConvertFrom-Json
    if($archPrior.State -ne 'SUCCEEDED' -or !$archPrior.Cosim -or $archPrior.PeriodNs -ne 10 -or
       $archPrior.Kernel -ne $pair[0] -or $archPrior.Part -ne 'xc7z015clg485-2') {throw 'Requires accepted matching 100 MHz baseline HLS jobs'}
}
if(!$Job) {
    $archName='{0}_architecture_stage1_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
    $Job=Join-Path $Orb60Root "build/optimized/comparison/$archName"
}
$archJob=[IO.Path]::GetFullPath($Job)
$archInputs=Join-Path $archJob 'inputs';New-Item -ItemType Directory -Path $archInputs -Force | Out-Null
$archState=[ordered]@{State='RUNNING';Stage='HOST';Job=$archJob;ProcessId=$PID;FrequencyMHz=100;
    BaselineLayer=[IO.Path]::GetFullPath($BaselineLayer);BaselineDescriptor=[IO.Path]::GetFullPath($BaselineDescriptor);
    Scope='8-bank reducer, lossless geometry runs, tournament selection, cross-point descriptor DATAFLOW; HLS gate only';
    StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-ArchitectureState {$archState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $archJob 'status.json') -Encoding UTF8}
Save-ArchitectureState
Write-Output "ORB60_ARCHITECTURE_JOB=$archJob PID=$PID"
try {
    $archFiles=@()
    foreach($name in @('architecture_stage1.ps1','hls.ps1','hls.tcl','host.ps1','compare_hls.py','compare_layer2.py','compare_descriptor.py','compare_architecture.py','environment.ps1')) {
        $archFile=Join-Path $PSScriptRoot $name;Copy-Item -LiteralPath $archFile -Destination $archInputs
        $archFiles+=@{Path=$archFile;SHA256=(Get-FileHash -LiteralPath $archFile).Hash}
    }
    $archFiles | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $archJob 'tool_manifest.json') -Encoding UTF8
    & $archShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'host.ps1') -Variant optimized *> (Join-Path $archJob 'host.log')
    if($LASTEXITCODE) {throw 'Host exact regression failed'}
    & (Join-Path $Orb60Root 'build/optimized/host/next_descriptor_stream_test.exe') $DescriptorVectors *> (Join-Path $archJob 'descriptor_native.log')
    if($LASTEXITCODE) {throw 'Independent 38-transaction native descriptor regression failed'}
    foreach($kernel in @('layer2','descriptor')) {
        $archState.Stage="HLS_$kernel";Save-ArchitectureState
        $archChildFile=Join-Path $archJob "${kernel}_job.txt"
        $archArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'hls.ps1'),
            '-Variant','optimized','-Kernel',$kernel,'-Period','10','-Cosim','-JobFile',$archChildFile)
        if($kernel -eq 'descriptor') {$archArgs+=@('-DescriptorVectors',$DescriptorVectors)}
        & $archShell @archArgs *> (Join-Path $archJob "${kernel}_hls.log")
        if($LASTEXITCODE) {throw "Architecture $kernel HLS failed; see ${kernel}_hls.log"}
        $archChild=(Get-Content -LiteralPath $archChildFile -Raw).Trim()
        $archChildState=Get-Content -LiteralPath (Join-Path $archChild 'status.json') -Raw | ConvertFrom-Json
        if($archChildState.State -ne 'SUCCEEDED' -or !$archChildState.Cosim -or $archChildState.PeriodNs -ne 10 -or $archChildState.Kernel -ne $kernel) {throw 'Missing exact matching child HLS acceptance'}
        $archCandidate=Join-Path $archJob "accepted_$kernel";New-Item -ItemType Directory -Path $archCandidate | Out-Null
        $archCompareArgs=@('--job',$archChild,'--output',(Join-Path $archCandidate 'comparison.json'))
        if($kernel -eq 'layer2') {$archCompareArgs+=@('--front2',$Front2Hls)}
        & $ProjectPython (Join-Path $archInputs "compare_$kernel.py") @archCompareArgs *> (Join-Path $archJob "${kernel}_compare.log")
        if($LASTEXITCODE) {throw "Architecture $kernel actual-II/64-bit gate failed"}
        $archAccepted=[ordered]@{State='SUCCEEDED';Scope='Exact C/RTL + actual II/interface only; protocol/frame/route pending'}
        if($kernel -eq 'layer2') {$archAccepted['layer2Job']=$archChild}
        else {$archAccepted['DescriptorHlsJob']=$archChild}
        $archAccepted | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $archCandidate 'status.json') -Encoding UTF8
        $archState["${kernel}HlsJob"]=$archChild;Save-ArchitectureState
    }
    $archState.Stage='COMPARE';Save-ArchitectureState
    & $ProjectPython (Join-Path $archInputs 'compare_architecture.py') --layer $archState.layer2HlsJob `
        --descriptor $archState.descriptorHlsJob --old-layer $BaselineLayer --old-descriptor $BaselineDescriptor `
        --output (Join-Path $archJob 'comparison.json') *> (Join-Path $archJob 'compare.log')
    if($LASTEXITCODE) {throw 'Architecture stage/latency/resource post-check failed'}
    foreach($archEntry in $archFiles) {
        if((Get-FileHash -LiteralPath $archEntry.Path).Hash -ne $archEntry.SHA256) {throw 'Gate tool changed while running'}
    }
    $archState.State='SUCCEEDED';$archState.Stage='HLS_GATES_COMPLETE'
} catch {$archState.State='FAILED';$archState['Error']=$_.Exception.Message;throw}
finally {$archState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-ArchitectureState}
