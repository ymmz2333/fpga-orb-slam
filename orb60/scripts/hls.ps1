[CmdletBinding()]
param(
    [ValidateSet('baseline','optimized')][string]$Variant='baseline',
    [ValidateSet('front','front2','layer2','descriptor','merge4','resize','gaussian','all')][string]$Kernel='all',
    [ValidateRange(5,20)][double]$Period=10,
    [switch]$Cosim,
    [switch]$CsimOnly,
    [string]$DescriptorVectors='',
    [string]$JobFile='',
    [string]$SourceJob='',
    [string]$SourceProbe='',
    [ValidateSet(0,1,2)][int]$DescriptorWidthMode=0,
    [ValidateSet(0,2,4,8)][int]$DescriptorPrefetch=0,
    [switch]$DescriptorPatch32,
    [ValidateSet(0,1,2)][int]$DescriptorMomentFusion=0,
    [ValidateSet(0,1)][int]$DescriptorFastQuantize=0,
    [ValidateSet(0,1,2,3)][int]$SliceCompactMode=0,
    [string]$AuthorRoot='',
    [ValidateSet(2,4)][int]$LayerPpc=2,
    [switch]$FastStaged,
    [switch]$LayerIoOverlap,
    [switch]$LayerBramFifos,
    [switch]$NoExport
)
. (Join-Path $PSScriptRoot 'environment.ps1')
if ($Cosim -and $CsimOnly) { throw 'Choose CsimOnly or Cosim' }
if($SourceJob -and $SourceProbe) {throw 'Choose an accepted SourceJob or a directional SourceProbe'}
if($DescriptorWidthMode -ne 0 -and $Kernel -ne 'descriptor') {throw 'Descriptor width experiments require the descriptor kernel'}
if($DescriptorPrefetch -ne 0 -and $Kernel -ne 'descriptor') {throw 'Descriptor prefetch experiments require the descriptor kernel'}
if($DescriptorPatch32 -and ($Kernel -ne 'descriptor' -or $Variant -ne 'optimized')) {throw 'Patch32 requires optimized descriptor'}
if($DescriptorMomentFusion -and ($Kernel -ne 'descriptor' -or $Variant -ne 'optimized' -or !$DescriptorPrefetch)) {throw 'Moment fusion requires optimized descriptor and manual-burst prefetch'}
if($DescriptorFastQuantize -and $Kernel -ne 'descriptor') {throw 'A32 quantizer requires descriptor kernel'}
if($SliceCompactMode -and $Kernel -ne 'layer2') {throw 'Compact tournament requires layer kernel'}
if($AuthorRoot -and ($SourceJob -or $SourceProbe)) {throw 'Choose author source or frozen replay'}
if($LayerPpc -eq 4 -and ($Kernel -ne 'layer2' -or $Variant -ne 'optimized')) {throw '4PPC requires the optimized layer top'}
if($FastStaged -and $Kernel -notin @('front','front2','layer2')) {throw 'FAST stages require a front/layer kernel'}
if(($LayerIoOverlap -or $LayerBramFifos) -and ($Kernel -ne 'layer2' -or $LayerPpc -ne 4)) {throw 'Image overlap/BRAM FIFO choices require the4PPC layer'}
$jobName = '{0}_{1}_{2}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$Kernel,([guid]::NewGuid().ToString('N').Substring(0,8))
$job = Join-Path $Orb60Root "build/$Variant/hls/$jobName"
$inputRoot = Join-Path $job 'inputs'
New-Item -ItemType Directory -Path $inputRoot -Force | Out-Null
# Every job compiles a frozen snapshot, including the independent reference.
if($SourceJob -or $SourceProbe) {
    $replayRoot=[IO.Path]::GetFullPath($(if($SourceJob) {$SourceJob} else {$SourceProbe}))
    $replayState=Get-Content -LiteralPath (Join-Path $replayRoot 'status.json') -Raw | ConvertFrom-Json
    if($replayState.State -ne 'SUCCEEDED' -or $replayState.Kernel -ne $Kernel -or
       $replayState.Variant -ne $Variant -or $replayState.Part -ne 'xc7z015clg485-2') {throw 'SourceJob must be a paired accepted HLS snapshot'}
    if($SourceJob -and !$replayState.Cosim) {throw 'SourceJob requires exact co-sim acceptance'}
    if($SourceProbe -and ($replayState.Cosim -or !$replayState.NoExport -or $replayState.PeriodNs -ne $Period -or
       !(Test-Path -LiteralPath (Join-Path $replayRoot "projects/$Kernel/solution1/syn/report/fastv2_${Kernel}_hls_csynth.xml")))) {
        throw 'SourceProbe must be a successful no-export CSim/synthesis probe at the same clock; all gates run anew'
    }
    $replayWidth=if($null -ne $replayState.DescriptorWidthMode) {[int]$replayState.DescriptorWidthMode} else {0}
    if($replayWidth -ne $DescriptorWidthMode) {throw 'Replay must explicitly preserve the source width mode'}
    $replayPrefetch=if($null -ne $replayState.DescriptorPrefetch) {[int]$replayState.DescriptorPrefetch} else {0}
    if($replayPrefetch -ne $DescriptorPrefetch) {throw 'Replay must explicitly preserve the source prefetch mode'}
    if([int]$replayState.DescriptorMomentFusion -ne $DescriptorMomentFusion) {throw 'Replay must preserve raw moment fusion mode'}
    if([int]$replayState.DescriptorFastQuantize -ne $DescriptorFastQuantize -or [int]$replayState.SliceCompactMode -ne $SliceCompactMode) {throw 'Replay must preserve quantizer and compact tournament modes'}
    $replayPpc=if($null -ne $replayState.LayerPpc) {[int]$replayState.LayerPpc} else {2}
    if($replayPpc -ne $LayerPpc -or [bool]$replayState.FastStaged -ne [bool]$FastStaged -or [bool]$replayState.DescriptorPatch32 -ne [bool]$DescriptorPatch32) {throw 'Replay must preserve PPC, FAST staging and patch organization'}
    if([bool]$replayState.LayerIoOverlap -ne [bool]$LayerIoOverlap -or [bool]$replayState.LayerBramFifos -ne [bool]$LayerBramFifos) {throw 'Replay must preserve image I/O and FIFO choices'}
    foreach($entry in (Get-Content -LiteralPath (Join-Path $replayRoot 'source_manifest.json') -Raw | ConvertFrom-Json)) {
        if((Get-FileHash -LiteralPath (Join-Path $replayRoot ('inputs/'+$entry.Path))).Hash -ne $entry.SHA256) {throw 'Replay source hash changed'}
    }
    foreach($item in Get-ChildItem -LiteralPath (Join-Path $replayRoot 'inputs')) {
        Copy-Item -LiteralPath $item.FullName -Destination $inputRoot -Recurse
    }
} else {
$author=if($AuthorRoot) {[IO.Path]::GetFullPath($AuthorRoot)} else {Join-Path $Orb60Root $Variant}
Copy-Item -LiteralPath (Join-Path $author 'FPGA_ORB_HLS') -Destination $inputRoot -Recurse
Copy-Item -LiteralPath (Join-Path $author 'FPGA_ORB_SHARED_v1.0') -Destination $inputRoot -Recurse
$vectors = if($AuthorRoot) {Join-Path $author 'front_vectors.inc'} else {Join-Path $Orb60Root "build/$Variant/host/generated/front_vectors.inc"}
if (!(Test-Path -LiteralPath $vectors)) { throw 'Run host.ps1 first to generate independent front vectors' }
Copy-Item -LiteralPath $vectors -Destination (Join-Path $inputRoot 'front_vectors.inc')
if ($Kernel -eq 'front2') {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "build/$Variant/host/generated/front2_vectors.inc") -Destination (Join-Path $inputRoot 'front2_vectors.inc')
}
if ($Kernel -eq 'layer2') {
    $layerVectors=if($AuthorRoot) {Join-Path $author 'layer2_vectors.inc'} else {Join-Path $Orb60Root "build/$Variant/host/generated/layer2_vectors.inc"}
    Copy-Item -LiteralPath $layerVectors -Destination (Join-Path $inputRoot 'layer2_vectors.inc')
}
}
if ($Kernel -eq 'descriptor') {
    if (!$DescriptorVectors -or !(Test-Path -LiteralPath (Join-Path $DescriptorVectors 'vectors.json'))) {throw 'Requires independent descriptor vectors'}
    Copy-Item -LiteralPath $DescriptorVectors -Destination (Join-Path $job 'descriptor_vectors') -Recurse
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'hls.tcl') -Destination $job
$hashes = Get-ChildItem -LiteralPath $inputRoot -Recurse -File | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($inputRoot.Length+1); SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$hashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $job 'source_manifest.json') -Encoding UTF8
$state = [ordered]@{State='RUNNING';Variant=$Variant;Kernel=$Kernel;PeriodNs=$Period;Cosim=[bool]$Cosim;StartedUtc=[DateTime]::UtcNow.ToString('o');Part='xc7z015clg485-2';Tool=$VitisHlsBat;Job=$job;SourceJob=$SourceJob}
$state['DescriptorWidthMode']=$DescriptorWidthMode;$state['NoExport']=[bool]$NoExport
$state['DescriptorPrefetch']=$DescriptorPrefetch;$state['ProcessId']=$PID
$state['DescriptorMomentFusion']=$DescriptorMomentFusion
$state['DescriptorFastQuantize']=$DescriptorFastQuantize;$state['SliceCompactMode']=$SliceCompactMode;$state['AuthorRoot']=$AuthorRoot
$state['SourceProbe']=$SourceProbe;$state['CsimOnly']=[bool]$CsimOnly
$state['LayerPpc']=$LayerPpc;$state['FastStaged']=[bool]$FastStaged;$state['DescriptorPatch32']=[bool]$DescriptorPatch32
$state['LayerIoOverlap']=[bool]$LayerIoOverlap;$state['LayerBramFifos']=[bool]$LayerBramFifos
$state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job 'status.json') -Encoding UTF8
if($JobFile) {$job | Set-Content -LiteralPath $JobFile -Encoding UTF8}
$env:ORB60_HLS_JOB=$job.Replace('\','/')
$env:ORB60_HLS_KERNEL=$Kernel
$env:ORB60_HLS_PERIOD=$Period.ToString([Globalization.CultureInfo]::InvariantCulture)
$env:ORB60_HLS_COSIM=[int][bool]$Cosim
$env:ORB60_HLS_CSIM_ONLY=[int][bool]$CsimOnly
$env:ORB60_DESCRIPTOR_WIDTH_MODE=$DescriptorWidthMode
$env:ORB60_DESCRIPTOR_PREFETCH=$DescriptorPrefetch
$env:ORB60_DESCRIPTOR_PATCH32=[int][bool]$DescriptorPatch32
$env:ORB60_DESCRIPTOR_MOMENT_FUSION=$DescriptorMomentFusion
$env:ORB60_DESCRIPTOR_FAST_QUANTIZE=$DescriptorFastQuantize;$env:ORB60_SLICE_COMPACT_MODE=$SliceCompactMode
$env:ORB60_LAYER_PPC=$LayerPpc;$env:ORB60_FAST_STAGED=[int][bool]$FastStaged
$env:ORB60_LAYER_IO_OVERLAP=[int][bool]$LayerIoOverlap;$env:ORB60_LAYER_BRAM_FIFOS=[int][bool]$LayerBramFifos
$env:ORB60_HLS_NO_EXPORT=[int][bool]$NoExport
Write-Output "ORB60_HLS_JOB=$job"
Push-Location $job
try {
    if ($Kernel -eq 'layer2') {
        & $ProjectPython (Join-Path $Orb60Root 'tests/prepare_layer2.py') $job (Join-Path $job 'oracle_vectors')
        if ($LASTEXITCODE -ne 0) {throw 'Layer2 independent Python oracle failed'}
    }
    # Use the native no-log option: AMD's Windows launcher otherwise invokes
    # the unrelated MSYS tee on PATH. We retain the complete log ourselves.
    $ErrorActionPreference='Continue'
    & $VitisHlsBat -nolog -f (Join-Path $job 'hls.tcl') 2>&1 | Tee-Object -FilePath (Join-Path $job 'tool.log')
    $toolExit=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if ($toolExit -ne 0 -or !(Test-Path -LiteralPath (Join-Path $job 'success.stamp'))) { throw "HLS failed (exit $toolExit)" }
    $state.State='SUCCEEDED'
} catch {
    $state.State='FAILED'; $state['Error']=$_.Exception.Message
    throw
} finally {
    Pop-Location
    $state['FinishedUtc']=[DateTime]::UtcNow.ToString('o')
    $state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $job 'status.json') -Encoding UTF8
}
