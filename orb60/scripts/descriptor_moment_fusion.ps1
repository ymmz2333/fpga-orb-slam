[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineDescriptor,[string]$Job='',
      [ValidateSet(8,10)][int]$Period=8)
. (Join-Path $PSScriptRoot 'environment.ps1')
$fusionBase=[IO.Path]::GetFullPath($BaselineDescriptor)
$fusionPrior=Get-Content -LiteralPath (Join-Path $fusionBase 'status.json') -Raw | ConvertFrom-Json
if($fusionPrior.State -ne 'SUCCEEDED' -or !$fusionPrior.Cosim -or $fusionPrior.PeriodNs -ne $Period -or
   $fusionPrior.DescriptorWidthMode -ne 2 -or $fusionPrior.DescriptorPrefetch -ne 8 -or !$fusionPrior.DescriptorPatch32) {
    throw 'Requires paired accepted width2/prefetch8/patch32 descriptor at the comparison clock'
}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_moment_fusion_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$fusionJob=[IO.Path]::GetFullPath($Job);New-Item -ItemType Directory -Path $fusionJob -Force | Out-Null
$fusionState=[ordered]@{State='RUNNING';Stage='HOST_ORACLE';ProcessId=$PID;Job=$fusionJob;BaselineDescriptor=$fusionBase;PeriodNs=$Period;
    Scope='Candidate-only independent moment/38-record checks and bounded HLS probes; protocol/frame/route/board pending';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-FusionState {$fusionState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $fusionJob 'status.json') -Encoding UTF8}
Save-FusionState;Write-Output "ORB60_MOMENT_FUSION_JOB=$fusionJob PID=$PID"
$fusionShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$fusionLiveSource=Join-Path $Orb60Root 'optimized/FPGA_ORB_HLS/fastv2/next'
$fusionSource=Join-Path $fusionJob 'host_inputs/next'
$fusionRef=Join-Path $fusionJob 'host_inputs/reference'
New-Item -ItemType Directory -Path $fusionSource,$fusionRef -Force | Out-Null
foreach($directory in @('src','include','host','hls')) {Copy-Item -LiteralPath (Join-Path $fusionLiveSource $directory) -Destination $fusionSource -Recurse}
Copy-Item -LiteralPath (Join-Path $Orb60Root 'optimized/FPGA_ORB_SHARED_v1.0/constants.hpp') -Destination $fusionRef
$fusionHashes=Get-ChildItem -LiteralPath (Join-Path $fusionJob 'host_inputs') -File -Recurse | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($fusionJob.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$fusionHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $fusionJob 'host_source_manifest.json') -Encoding UTF8
foreach($file in @('descriptor_moment_fusion.ps1','compare_moment_fusion.py','hls.ps1','hls.tcl')) {Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $fusionJob}
$fusionFlags=@('-std=c++17','-O2','-Wno-unknown-pragmas','-Wno-unused-label','-DORB60_DESCRIPTOR_WIDTH_MODE=2',
    '-DORB60_DESCRIPTOR_PREFETCH=8','-DORB60_DESCRIPTOR_PATCH32=1','-DORB60_DESCRIPTOR_MOMENT_FUSION=1',
    ('-I'+(Join-Path $fusionSource 'include')),('-I'+$fusionRef))
try {
    & $Orb60Cxx @fusionFlags (Join-Path $fusionSource 'host/test_raw_moment_fusion.cpp') -o (Join-Path $fusionJob 'raw_moments.exe') *> (Join-Path $fusionJob 'host_compile.log')
    if($LASTEXITCODE) {throw 'Fused moment oracle build failed'}
    & (Join-Path $fusionJob 'raw_moments.exe') *> (Join-Path $fusionJob 'host_moments.log')
    if($LASTEXITCODE) {throw 'Independent scalar-image/fused moment oracle mismatch'}
    & $Orb60Cxx @fusionFlags (Join-Path $fusionSource 'src/descriptor_hls.cpp') (Join-Path $fusionSource 'hls/tb_descriptor_stream.cpp') -o (Join-Path $fusionJob 'descriptor_stream.exe') *> (Join-Path $fusionJob 'stream_compile.log')
    if($LASTEXITCODE) {throw 'Fused external record oracle build failed'}
    & (Join-Path $fusionJob 'descriptor_stream.exe') (Join-Path $fusionBase 'descriptor_vectors') *> (Join-Path $fusionJob 'host_records.log')
    if($LASTEXITCODE) {throw 'Frozen independent descriptor record/error-prefix mismatch'}
    foreach($mode in @(1,2)) {
        $fusionState.Stage="CSIM_SYNTH_FUSION$mode";Save-FusionState
        & $fusionShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -Period $Period -DescriptorVectors (Join-Path $fusionBase 'descriptor_vectors') -DescriptorWidthMode 2 -DescriptorPrefetch 8 -DescriptorPatch32 -DescriptorMomentFusion $mode -NoExport -JobFile (Join-Path $fusionJob "mode${mode}_job.txt") *> (Join-Path $fusionJob "mode${mode}.log")
        if($LASTEXITCODE) {throw "Fused mode$mode exact CSim/synthesis failed"}
        $fusionState["Mode${mode}HlsJob"]=(Get-Content -LiteralPath (Join-Path $fusionJob "mode${mode}_job.txt") -Raw).Trim();Save-FusionState
    }
    $fusionState.Stage='PROBE_COMPARE';Save-FusionState
    & $ProjectPython (Join-Path $PSScriptRoot 'compare_moment_fusion.py') --baseline $fusionBase --jobs $fusionState.Mode1HlsJob $fusionState.Mode2HlsJob --output (Join-Path $fusionJob 'comparison.json') *> (Join-Path $fusionJob 'compare.log')
    if($LASTEXITCODE) {throw 'Fused receiver II/interface/source/ownership probe gate failed'}
    $fusionState.State='SUCCEEDED';$fusionState.Stage='FUSION_PROBES_COMPLETE'
} catch {$fusionState.State='FAILED';$fusionState['Error']=$_.Exception.Message;throw}
finally {$fusionState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-FusionState}
