[CmdletBinding()]
param([ValidateRange(5,8)][double]$Period=(1000.0/150),[string]$AuthorRoot='',
      [Parameter(Mandatory=$true)][string]$DescriptorVectors,[string]$BackendJob='',
      [string]$LayerJob='',[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
if(!$AuthorRoot) {$AuthorRoot=Join-Path $Orb60Root 'experiments/frequency_headroom'}
$pairRoot=Join-Path $Orb60Root ('build/optimized/comparison/{0}_frequency_pair_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))
New-Item -ItemType Directory -Path $pairRoot -Force | Out-Null
$pairState=[ordered]@{State='RUNNING';Stage='DESCRIPTOR_HLS';Job=$pairRoot;PeriodNs=$Period;
    NominalFrequencyMHz=1000.0/$Period;AuthorRoot=$AuthorRoot;StartedUtc=[DateTime]::UtcNow.ToString('o');
    Scope='Fresh same-clock4PPC mode2 + fused exact fast-A32 backend; C/RTL and II/interface only; protocol/frame/route pending'}
function Save-PairState {$pairState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $pairRoot 'status.json') -Encoding UTF8}
Save-PairState;if($JobFile) {$pairRoot | Set-Content -LiteralPath $JobFile -Encoding UTF8}
Write-Output "ORB60_FREQUENCY_PAIR=$pairRoot PERIOD_NS=$Period"
$pairShell=(Get-Command pwsh.exe).Source
try {
    if($BackendJob) {
        $pairBackend=Get-Content -LiteralPath (Join-Path $BackendJob 'status.json') -Raw | ConvertFrom-Json
        if($pairBackend.State -ne 'SUCCEEDED' -or !$pairBackend.Cosim -or $pairBackend.NoExport -or
           $pairBackend.Kernel -ne 'descriptor' -or $pairBackend.Part -ne 'xc7z015clg485-2' -or
           [Math]::Abs($pairBackend.PeriodNs-$Period) -gt 1e-9 -or $pairBackend.DescriptorWidthMode -ne 2 -or
           $pairBackend.DescriptorPrefetch -ne 8 -or !$pairBackend.DescriptorPatch32 -or
           $pairBackend.DescriptorMomentFusion -ne 1 -or $pairBackend.DescriptorFastQuantize -ne 1) {throw 'Backend reuse requires exact same-clock accepted descriptor'}
        foreach($entry in (Get-Content -LiteralPath (Join-Path $BackendJob 'source_manifest.json') -Raw | ConvertFrom-Json)) {
            $priorInput=Join-Path $BackendJob ('inputs/'+$entry.Path)
            if((Get-FileHash -LiteralPath $priorInput).Hash -ne $entry.SHA256) {throw 'Backend frozen source changed'}
            # The frontend may change; all backend sources/headers/reference inputs stay identical.
            if($entry.Path -match '[/\\]include[/\\]|[/\\]descriptor_hls\.cpp$|^FPGA_ORB_SHARED') {
                if((Get-FileHash -LiteralPath (Join-Path $AuthorRoot $entry.Path)).Hash -ne $entry.SHA256) {throw ('Backend author dependency differs: '+$entry.Path)}
            }
        }
        if((Get-FileHash -LiteralPath (Join-Path $BackendJob 'descriptor_vectors/vectors.json')).Hash -ne
           (Get-FileHash -LiteralPath (Join-Path $DescriptorVectors 'vectors.json')).Hash) {throw 'Backend vector metadata changed'}
        [IO.Path]::GetFullPath($BackendJob) | Set-Content -LiteralPath (Join-Path $pairRoot 'descriptor_hls_job.txt') -Encoding UTF8
        $pairState['DescriptorReusedFrom']=[IO.Path]::GetFullPath($BackendJob)
        $pairState.Scope='Same-clock immutable backend reused by source/header/vector hashes; fresh frontend C/RTL; joint protocol/frame/route pending'
    } else {
        & $pairShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel descriptor -Period $Period -Cosim -AuthorRoot $AuthorRoot -DescriptorVectors $DescriptorVectors -DescriptorWidthMode 2 -DescriptorPrefetch 8 -DescriptorPatch32 -DescriptorMomentFusion 1 -DescriptorFastQuantize 1 -JobFile (Join-Path $pairRoot 'descriptor_hls_job.txt') *> (Join-Path $pairRoot 'descriptor.log')
        if($LASTEXITCODE) {throw 'High-clock descriptor C/RTL/export failed'}
    }
    $pairDesc=(Get-Content -LiteralPath (Join-Path $pairRoot 'descriptor_hls_job.txt') -Raw).Trim();$pairState['DescriptorHlsJob']=$pairDesc
    $pairState.Stage='LAYER_HLS';Save-PairState;Write-Output 'DESCRIPTOR_C_RTL_COMPLETE; LAYER_HLS_STARTED'
    if($LayerJob) {
        $pairFront=Get-Content -LiteralPath (Join-Path $LayerJob 'status.json') -Raw | ConvertFrom-Json
        if($pairFront.State -ne 'SUCCEEDED' -or !$pairFront.Cosim -or $pairFront.NoExport -or
           $pairFront.Kernel -ne 'layer2' -or $pairFront.Part -ne 'xc7z015clg485-2' -or
           [Math]::Abs($pairFront.PeriodNs-$Period) -gt 1e-9 -or $pairFront.LayerPpc -ne 4 -or
           !$pairFront.FastStaged -or !$pairFront.LayerIoOverlap -or !$pairFront.LayerBramFifos -or
           $pairFront.SliceCompactMode -ne 2) {throw 'Frontend reuse requires accepted same-clock4PPC configuration'}
        foreach($entry in (Get-Content -LiteralPath (Join-Path $LayerJob 'source_manifest.json') -Raw | ConvertFrom-Json)) {
            if((Get-FileHash -LiteralPath (Join-Path $LayerJob ('inputs/'+$entry.Path))).Hash -ne $entry.SHA256) {throw 'Frontend frozen source changed'}
            # layer2_hls.cpp includes frontend CPP/headers; descriptor CPP is
            # a separate top and may change. Verify all frontend dependencies.
            if(($entry.Path -match '[/\\](src|include)[/\\]' -and $entry.Path -notmatch '[/\\]descriptor_hls\.cpp$') -or
               $entry.Path -match '^FPGA_ORB_SHARED|^(front|layer2)_vectors\.inc$|[/\\]hls[/\\]') {
                if((Get-FileHash -LiteralPath (Join-Path $AuthorRoot $entry.Path)).Hash -ne $entry.SHA256) {throw ('Frontend author dependency differs: '+$entry.Path)}
            }
        }
        [IO.Path]::GetFullPath($LayerJob) | Set-Content -LiteralPath (Join-Path $pairRoot 'layer_hls_job.txt') -Encoding UTF8
        $pairState['LayerReusedFrom']=[IO.Path]::GetFullPath($LayerJob)
        $pairState.Scope='Same-clock accepted cores paired by immutable source/dependency hashes; joint protocol/frame/route pending'
    } else {
        & $pairShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel layer2 -Period $Period -Cosim -AuthorRoot $AuthorRoot -LayerPpc 4 -FastStaged -LayerIoOverlap -LayerBramFifos -SliceCompactMode 2 -JobFile (Join-Path $pairRoot 'layer_hls_job.txt') *> (Join-Path $pairRoot 'layer.log')
        if($LASTEXITCODE) {throw 'High-clock layer C/RTL/export failed'}
    }
    $pairLayer=(Get-Content -LiteralPath (Join-Path $pairRoot 'layer_hls_job.txt') -Raw).Trim();$pairState['LayerHlsJob']=$pairLayer
    foreach($core in @('layer','descriptor')) {
        $pairCarrier=Join-Path $pairRoot "accepted_$core";New-Item -ItemType Directory -Path $pairCarrier -Force | Out-Null
        $pairHls=if($core -eq 'layer') {$pairLayer} else {$pairDesc}
        $pairCompare=if($core -eq 'layer') {'compare_layer2.py'} else {'compare_descriptor.py'}
        & $ProjectPython (Join-Path $PSScriptRoot $pairCompare) --job $pairHls --output (Join-Path $pairCarrier 'comparison.json') *> (Join-Path $pairRoot "compare_$core.log")
        if($LASTEXITCODE) {throw "Actual $core II/interface check failed"}
        $pairProof=[ordered]@{State='SUCCEEDED';PeriodNs=$Period;FrequencyMHz=1000.0/$Period;Scope='Validated accepted C/RTL/II/interface; protocol/frame/route pending'}
        if($core -eq 'layer') {$pairProof['layer2Job']=$pairHls} else {$pairProof['DescriptorHlsJob']=$pairHls}
        $pairProof | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $pairCarrier 'status.json') -Encoding UTF8
    }
    $pairState.State='SUCCEEDED';$pairState.Stage='C_RTL_PAIR_COMPLETE';Write-Output 'HIGH_CLOCK_C_RTL_PAIR_COMPLETE'
} catch {$pairState.State='FAILED';$pairState['Error']=$_.Exception.Message;throw}
finally {$pairState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-PairState}
