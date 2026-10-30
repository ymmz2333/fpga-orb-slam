[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BaselineDescriptor,[string]$Job='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$prefetchShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$prefetchPrior=Get-Content -LiteralPath (Join-Path $BaselineDescriptor 'status.json') -Raw | ConvertFrom-Json
if($prefetchPrior.State -ne 'SUCCEEDED' -or !$prefetchPrior.Cosim -or $prefetchPrior.Kernel -ne 'descriptor' -or $prefetchPrior.PeriodNs -ne 10) {throw 'Requires retained exact 100MHz descriptor; no baseline rerun'}
if(!$Job) {$Job=Join-Path $Orb60Root ('build/optimized/comparison/{0}_descriptor_prefetch_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))}
$prefetchJob=[IO.Path]::GetFullPath($Job)
if(Test-Path -LiteralPath (Join-Path $prefetchJob 'status.json')) {throw 'Refusing an existing prefetch experiment'}
$prefetchInputs=Join-Path $prefetchJob 'inputs';New-Item -ItemType Directory -Path $prefetchInputs -Force | Out-Null
foreach($name in @('descriptor_prefetch_experiment.ps1','compare_descriptor_prefetch.py','compare_descriptor_width_probes.py','compare_hls.py','compare_descriptor.py','hls.ps1','hls.tcl')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $prefetchInputs
}
Copy-Item -LiteralPath (Join-Path $Orb60Root 'docs/NEXT_OPTIMIZATION_PLAN_ZH.md') -Destination (Join-Path $prefetchInputs 'plan_snapshot.md')
$prefetchState=[ordered]@{State='RUNNING';Stage='HLS_PREFETCH2';Job=$prefetchJob;ProcessId=$PID;BaselineDescriptor=$BaselineDescriptor;
    Scope='Directional manual row-request/receive custom HLS matrix2/4/8; exact RTL gates only, real AXI occupancy/frame/route pending';StartedUtc=[DateTime]::UtcNow.ToString('o')}
function Save-PrefetchState {$prefetchState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $prefetchJob 'status.json') -Encoding UTF8}
Save-PrefetchState;Write-Output "ORB60_DESCRIPTOR_PREFETCH_JOB=$prefetchJob PID=$PID"
$prefetchLive=Join-Path $Orb60Root 'optimized/FPGA_ORB_HLS'
$prefetchHashes=Get-ChildItem -LiteralPath $prefetchLive -Recurse -File | ForEach-Object {@{Path=$_.FullName;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}}
$prefetchHashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $prefetchJob 'source_start_manifest.json') -Encoding UTF8
$prefetchTools=Get-ChildItem -LiteralPath $prefetchInputs -File | ForEach-Object {@{Path=$_.Name;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}}
$prefetchTools | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $prefetchJob 'tool_manifest.json') -Encoding UTF8
try {
    $prefetchChildren=@()
    foreach($depth in @(2,4,8)) {
        foreach($entry in $prefetchHashes) {if((Get-FileHash -LiteralPath $entry.Path).Hash -ne $entry.SHA256) {throw 'Live source changed between bounded variants; no mixed comparison'}}
        $prefetchState.Stage="HLS_PREFETCH$depth";Save-PrefetchState
        $childFile=Join-Path $prefetchJob "prefetch${depth}_job.txt"
        & $prefetchShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -Period 10 -DescriptorVectors (Join-Path $BaselineDescriptor 'descriptor_vectors') -DescriptorWidthMode 0 -DescriptorPrefetch $depth -Cosim -JobFile $childFile *> (Join-Path $prefetchJob "prefetch${depth}.log")
        if($LASTEXITCODE) {throw "Manual prefetch$depth CSim/synthesis/co-sim failed; original child evidence retained"}
        $child=(Get-Content -LiteralPath $childFile -Raw).Trim();$prefetchChildren+=,$child
        $prefetchState["Prefetch${depth}HlsJob"]=$child;Save-PrefetchState
        & $ProjectPython (Join-Path $prefetchInputs 'compare_descriptor.py') --job $child --output (Join-Path $prefetchJob "prefetch${depth}_hls_comparison.json") *> (Join-Path $prefetchJob "prefetch${depth}_postcheck.log")
        if($LASTEXITCODE) {throw "Prefetch$depth existing exact-II/interface gate failed"}
    }
    $prefetchState.Stage='COMPARE';Save-PrefetchState
    & $ProjectPython (Join-Path $prefetchInputs 'compare_descriptor_prefetch.py') --baseline $BaselineDescriptor --jobs @prefetchChildren --output (Join-Path $prefetchJob 'comparison.json') *> (Join-Path $prefetchJob 'compare.log')
    if($LASTEXITCODE) {throw 'Actual manual-burst structure/II/register post-check failed'}
    $prefetchState.State='SUCCEEDED';$prefetchState.Stage='PREFETCH_HLS_GATES_COMPLETE'
} catch {$prefetchState.State='FAILED';$prefetchState['Error']=$_.Exception.Message;throw}
finally {$prefetchState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-PrefetchState}
