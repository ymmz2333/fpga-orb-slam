[CmdletBinding()]
param([ValidateSet(1,2,3)][int]$Mode=2,[switch]$Cosim,[switch]$NoExport,
      [string]$SourceProbe='',[string]$AuthorRoot='',[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$sliceName='{0}_layer2_slice{1}_{2}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$Mode,([guid]::NewGuid().ToString('N').Substring(0,8))
$sliceJob=Join-Path $Orb60Root "build/optimized/hls/$sliceName"
$sliceInputs=Join-Path $sliceJob 'inputs';New-Item -ItemType Directory -Path $sliceInputs -Force | Out-Null
$sliceAuthor=if($AuthorRoot) {[IO.Path]::GetFullPath($AuthorRoot)} else {Join-Path $Orb60Root 'experiments/slice_compact'}
if($SourceProbe) {
    $slicePrior=Get-Content -LiteralPath (Join-Path $SourceProbe 'status.json') -Raw | ConvertFrom-Json
    if($slicePrior.State -ne 'SUCCEEDED' -or $slicePrior.Cosim -or !$slicePrior.NoExport -or
       $slicePrior.SliceCompactMode -ne $Mode -or $slicePrior.PeriodNs -ne 8) {throw 'Requires successful same-mode8ns source probe'}
    foreach($entry in (Get-Content -LiteralPath (Join-Path $SourceProbe 'source_manifest.json') -Raw | ConvertFrom-Json)) {
        if((Get-FileHash -LiteralPath (Join-Path $SourceProbe ('inputs/'+$entry.Path))).Hash -ne $entry.SHA256) {throw 'Slice replay source hash changed'}
    }
    foreach($item in Get-ChildItem -LiteralPath (Join-Path $SourceProbe 'inputs')) {Copy-Item -LiteralPath $item.FullName -Destination $sliceInputs -Recurse}
    Copy-Item -LiteralPath (Join-Path $SourceProbe 'hls.tcl') -Destination $sliceJob
} else {
    foreach($name in @('FPGA_ORB_HLS','FPGA_ORB_SHARED_v1.0','front_vectors.inc','layer2_vectors.inc')) {
        Copy-Item -LiteralPath (Join-Path $sliceAuthor $name) -Destination $sliceInputs -Recurse
    }
    Copy-Item -LiteralPath (Join-Path $sliceAuthor 'hls_slice.tcl') -Destination (Join-Path $sliceJob 'hls.tcl')
}
$sliceHashes=Get-ChildItem -LiteralPath $sliceInputs -File -Recurse | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($sliceInputs.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$sliceHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sliceJob 'source_manifest.json') -Encoding UTF8
$sliceState=[ordered]@{State='RUNNING';Job=$sliceJob;Kernel='layer2';Variant='optimized';PeriodNs=8;Part='xc7z015clg485-2';
    Tool=$VitisHlsBat;ProcessId=$PID;Cosim=[bool]$Cosim;NoExport=[bool]$NoExport;SliceCompactMode=$Mode;SourceProbe=$SourceProbe;
    AuthorRoot=$sliceAuthor;LayerPpc=4;FastStaged=$true;LayerIoOverlap=$true;LayerBramFifos=$true;DescriptorWidthMode=0;DescriptorPrefetch=0;
    DescriptorPatch32=$false;DescriptorMomentFusion=0;StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-SliceHls {$sliceState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $sliceJob 'status.json') -Encoding UTF8}
Save-SliceHls;if($JobFile) {$sliceJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
Write-Output "ORB60_SLICE_HLS_JOB=$sliceJob PID=$PID"
$env:ORB60_HLS_JOB=$sliceJob.Replace('\','/');$env:ORB60_HLS_KERNEL='layer2';$env:ORB60_HLS_PERIOD='8'
$env:ORB60_HLS_COSIM=[int][bool]$Cosim;$env:ORB60_HLS_CSIM_ONLY=0;$env:ORB60_HLS_NO_EXPORT=[int][bool]$NoExport
$env:ORB60_SLICE_COMPACT_MODE=$Mode;$env:ORB60_LAYER_PPC=4;$env:ORB60_FAST_STAGED=1
$env:ORB60_LAYER_IO_OVERLAP=1;$env:ORB60_LAYER_BRAM_FIFOS=1
$env:ORB60_DESCRIPTOR_WIDTH_MODE=0;$env:ORB60_DESCRIPTOR_PREFETCH=0;$env:ORB60_DESCRIPTOR_PATCH32=0;$env:ORB60_DESCRIPTOR_MOMENT_FUSION=0
try {
    & $ProjectPython (Join-Path $Orb60Root 'tests/prepare_layer2.py') $sliceJob (Join-Path $sliceJob 'oracle_vectors') *> (Join-Path $sliceJob 'oracle.log')
    if($LASTEXITCODE) {throw 'Independent Slice-layer golden/vector check failed'}
    Push-Location $sliceJob
    try {
        $ErrorActionPreference='Continue'
        & $VitisHlsBat -nolog -f (Join-Path $sliceJob 'hls.tcl') 2>&1 | Tee-Object -FilePath (Join-Path $sliceJob 'tool.log')
        $sliceExit=$LASTEXITCODE;$ErrorActionPreference='Stop'
        if($sliceExit -ne 0 -or !(Test-Path -LiteralPath (Join-Path $sliceJob 'success.stamp'))) {throw "Slice HLS failed (exit $sliceExit)"}
    } finally {Pop-Location}
    $sliceState.State='SUCCEEDED'
} catch {$sliceState.State='FAILED';$sliceState['Error']=$_.Exception.Message;throw}
finally {$sliceState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-SliceHls}
