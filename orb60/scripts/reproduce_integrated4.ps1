[CmdletBinding()]
param([ValidateSet('Inputs','All')][string]$Mode='Inputs',[ValidateSet(100,125)][int]$FrequencyMHz=100)
. (Join-Path $PSScriptRoot 'environment.ps1')
$reproShell=(Get-Command pwsh.exe -ErrorAction Stop).Source
$reproPeriod=1000.0/$FrequencyMHz
$reproFixture=Join-Path $Orb60Root 'fixtures/integrated4'
if(!(Test-Path -LiteralPath (Join-Path $reproFixture 'benchmark/vectors/vectors.json'))) {throw 'Requires the integrated4 source/evidence package fixtures'}
$reproJob=Join-Path $Orb60Root ('build/optimized/comparison/{0}_reproduce4_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8)))
New-Item -ItemType Directory -Path (Join-Path $reproJob 'inputs'),(Join-Path $reproJob 'benchmark') -Force | Out-Null
$reproState=[ordered]@{State='RUNNING';Stage='INPUTS';Job=$reproJob;LayerPpc=4;FrequencyMHz=$FrequencyMHz;FastStaged=$true;LayerIoOverlap=$true;LayerBramFifos=$true;StartedUtc=[DateTime]::UtcNow.ToString('o');ProcessId=$PID;Scope='Independent rebuild from distributed exact sources; no PS or board operation'}
function Save-Repro {$reproState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reproJob 'status.json') -Encoding UTF8}
function Require-ReproExit([string]$stage) {if($LASTEXITCODE) {throw "Reproduction failed at $stage"}}
Save-Repro;Write-Output "REPRODUCE4_JOB=$reproJob"
try {
    Copy-Item -LiteralPath (Join-Path $reproFixture 'benchmark/vectors') -Destination (Join-Path $reproJob 'benchmark/vectors') -Recurse
    $reproBenchmark=Join-Path $reproJob 'benchmark'
    & $ProjectPython -c 'import json,hashlib,sys; from pathlib import Path; p=Path(sys.argv[1]); v=json.loads((p/"vectors.json").read_text()); assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==h for n,h in v["sha256"].items())' (Join-Path $reproBenchmark 'vectors')
    Require-ReproExit 'fixture hashes'
    [ordered]@{State='SUCCEEDED';Stage='IMPORTED_GOLDEN_FIXTURES';Scope='Byte-verified imported independent inputs/expected outputs; this import does not run any FPGA logic';OriginStatus=(Join-Path $reproFixture 'benchmark/origin_status.json')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reproBenchmark 'status.json') -Encoding UTF8
    $reproVectors=Join-Path $reproJob 'descriptor_vectors'
    & $ProjectPython (Join-Path $Orb60Root 'tests/prepare_descriptor.py') --images (Join-Path $reproBenchmark 'vectors') --constants (Join-Path $Orb60Root 'optimized/FPGA_ORB_SHARED_v1.0/constants.hpp') --output $reproVectors
    Require-ReproExit 'independent descriptor golden'
    $reproState['BenchmarkJob']=$reproBenchmark
    if($Mode -eq 'Inputs') {$reproState.State='SUCCEEDED';$reproState.Stage='INPUTS_ONLY';Save-Repro;return}
    & $reproShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'host.ps1') -Variant optimized *> (Join-Path $reproJob 'host.log')
    Require-ReproExit 'host vectors/tests'
    foreach($kernel in @('layer2','descriptor')) {
        $pointer=Join-Path $reproJob ($kernel+'_hls_job.txt')
        $reproArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'hls.ps1'),'-Variant','optimized','-Kernel',$kernel,'-Period',$reproPeriod.ToString([Globalization.CultureInfo]::InvariantCulture),'-Cosim','-JobFile',$pointer)
        if($kernel -eq 'layer2') {$reproArgs+=@('-LayerPpc','4','-FastStaged','-LayerIoOverlap','-LayerBramFifos')}
        else {$reproArgs+=@('-DescriptorWidthMode','2','-DescriptorPrefetch','8','-DescriptorPatch32','-DescriptorVectors',$reproVectors)}
        & $reproShell @reproArgs *> (Join-Path $reproJob ($kernel+'_hls.log'));Require-ReproExit "HLS $kernel"
        $child=(Get-Content -LiteralPath $pointer -Raw).Trim()
        $accepted=Join-Path $reproJob $(if($kernel -eq 'layer2') {'accepted_layer'} else {'accepted_descriptor'})
        New-Item -ItemType Directory -Path $accepted | Out-Null
        $checker=if($kernel -eq 'layer2') {'compare_layer2.py'} else {'compare_descriptor.py'}
        & $ProjectPython (Join-Path $PSScriptRoot $checker) --job $child --output (Join-Path $accepted 'comparison.json') *> (Join-Path $reproJob ($kernel+'_compare.log'))
        Require-ReproExit "II/interfaces $kernel"
        $reproAcceptedState=[ordered]@{State='SUCCEEDED';HlsJob=$child;PeriodNs=$reproPeriod;Scope='Fresh exact C/RTL and II/interface gates'}
        $reproAcceptedState[$(if($kernel -eq 'layer2') {'layer2Job'} else {'DescriptorHlsJob'})]=$child
        $reproAcceptedState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $accepted 'status.json') -Encoding UTF8
        $reproState[$(if($kernel -eq 'layer2') {'LayerHlsJob'} else {'DescriptorHlsJob'})]=$child
    }
    Copy-Item -LiteralPath (Join-Path $reproJob 'layer2_hls_job.txt') -Destination (Join-Path $reproJob 'layer_hls_job.txt')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compare_native_architecture.py') -Destination (Join-Path $reproJob 'inputs/compare_native_architecture.py')
    $reproState['BaselineFrameJob']=Join-Path $Orb60Root 'evidence/integrated4_100mhz/native'
    $reproState.Stage='JOINT_VERIFY';Save-Repro
    foreach($phase in @('Frame','Route')) {
        & $reproShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'finish_integrated4.ps1') -Job $reproJob -Mode $phase
        Require-ReproExit $phase
    }
    $mergePointer=Join-Path $reproJob 'merge_hls_job.txt'
    & $reproShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'hls.ps1') -Variant optimized -Kernel merge4 -Period $reproPeriod -Cosim -NoExport -JobFile $mergePointer *> (Join-Path $reproJob 'merge_hls.log')
    Require-ReproExit 'serializer exact C/RTL'
    $merge=(Get-Content -LiteralPath $mergePointer -Raw).Trim()
    & $reproShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'merge4_axis_gate.ps1') -HlsJob $merge -ProductionLayer $reproState.LayerHlsJob -JobFile (Join-Path $reproJob 'merge_axis_job.txt')
    Require-ReproExit 'serializer random AXIS/reset'
    $reproState.State='SUCCEEDED';$reproState.Stage='COMPUTER_GATES_COMPLETE'
    $reproState['RouteJob']=(Get-Content -LiteralPath (Join-Path $reproJob 'route_job.txt') -Raw).Trim()
    $reproState['FrameJob']=(Get-Content -LiteralPath (Join-Path $reproJob 'frame_job.txt') -Raw).Trim()
    $reproState['MergeAxisJob']=(Get-Content -LiteralPath (Join-Path $reproJob 'merge_axis_job.txt') -Raw).Trim();Save-Repro
    & $reproShell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'generate_verified_bit.ps1') -IntegratedJob $reproJob
    Require-ReproExit 'paired bitstream'
} catch {$reproState.State='FAILED';$reproState['Error']=$_.Exception.Message;throw}
finally {$reproState['FinishedUtc']=[DateTime]::UtcNow.ToString('o');Save-Repro}
