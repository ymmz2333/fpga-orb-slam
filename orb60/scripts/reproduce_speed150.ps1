[CmdletBinding()]
param([ValidateSet('Inputs','Hls','All')][string]$Mode='Inputs')
. (Join-Path $PSScriptRoot 'environment.ps1')
$speedAuthor=Join-Path $Orb60Root 'experiments/frequency_speed_joint'
$speedFixture=Join-Path $Orb60Root 'fixtures/speed_joint'
if(!(Test-Path -LiteralPath (Join-Path $speedFixture 'benchmark/vectors/vectors.json'))) {throw 'Requires the verified speed150 source/report/bit package'}
$speedJob=Join-Path $Orb60Root ('build/optimized/comparison/{0}_reproduce_speed150_{1}' -f (Get-Date -Format yyyyMMdd_HHmmss),([guid]::NewGuid().ToString('N').Substring(0,8)))
$speedBenchmark=Join-Path $speedJob 'benchmark';New-Item -ItemType Directory -Path $speedBenchmark -Force|Out-Null
Copy-Item -LiteralPath (Join-Path $speedFixture 'benchmark/vectors') -Destination (Join-Path $speedBenchmark 'vectors') -Recurse
& $ProjectPython -c 'import json,hashlib,sys;from pathlib import Path;p=Path(sys.argv[1]);v=json.loads((p/"vectors.json").read_text());assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==h for n,h in v["sha256"].items())' (Join-Path $speedBenchmark 'vectors')
if($LASTEXITCODE) {throw 'Independent fixture hashes failed'}
[ordered]@{State='SUCCEEDED';Stage='IMPORTED_GOLDEN_FIXTURES';Scope='Independent expected outputs imported by SHA only; no FPGA verification claim'}|ConvertTo-Json|Set-Content (Join-Path $speedBenchmark 'status.json') -Encoding UTF8
$speedVectors=Join-Path $speedJob 'descriptor_vectors'
& $ProjectPython (Join-Path $Orb60Root 'tests/prepare_descriptor.py') --images (Join-Path $speedBenchmark 'vectors') --constants (Join-Path $speedAuthor 'FPGA_ORB_SHARED_v1.0/constants.hpp') --output $speedVectors
if($LASTEXITCODE) {throw 'Independent descriptor golden preparation failed'}
if($Mode -eq 'Inputs') {Write-Output "SPEED150_INPUTS_ONLY=$speedJob";return}
& (Join-Path $PSScriptRoot 'frequency_pair.ps1') -Period (1000.0/150) -AuthorRoot $speedAuthor -DescriptorVectors $speedVectors -JobFile (Join-Path $speedJob 'paired_job.txt')
$speedPair=(Get-Content -LiteralPath (Join-Path $speedJob 'paired_job.txt') -Raw).Trim()
$speedState=Get-Content -LiteralPath (Join-Path $speedPair 'status.json') -Raw|ConvertFrom-Json
if($speedState.State -ne 'SUCCEEDED') {throw 'Fresh150MHz HLS pair failed'}
& $ProjectPython (Join-Path $PSScriptRoot 'compare_frequency_pair.py') --pair $speedPair --baseline-layer-registers (Join-Path $Orb60Root 'evidence/integrated4_125mhz/registers/xfastv2_layer2_hls_hw.h') --baseline-descriptor-registers (Join-Path $Orb60Root 'evidence/integrated4_125mhz/registers/xfastv2_descriptor_hls_hw.h') --output (Join-Path $speedPair 'structure_comparison.json')
if($LASTEXITCODE) {throw 'Fresh structure/register comparison failed'}
if($Mode -eq 'Hls') {Write-Output "SPEED150_HLS_ONLY=$speedPair";return}
& (Join-Path $PSScriptRoot 'datapath_axi_gate.ps1') -LayerHlsJob $speedState.LayerHlsJob -DescriptorHlsJob $speedState.DescriptorHlsJob -JobFile (Join-Path $speedPair 'protocol_job.txt')
$speedProtocol=(Get-Content -LiteralPath (Join-Path $speedPair 'protocol_job.txt') -Raw).Trim()
& (Join-Path $PSScriptRoot 'native_frame.ps1') -LayerHlsJob $speedState.LayerHlsJob -DescriptorHlsJob $speedState.DescriptorHlsJob -BenchmarkJob $speedBenchmark -ProtocolJob $speedProtocol -JobFile (Join-Path $speedPair 'frame_job.txt')
$speedFrame=(Get-Content -LiteralPath (Join-Path $speedPair 'frame_job.txt') -Raw).Trim()
& (Join-Path $PSScriptRoot 'board_ddr_frame.ps1') -FrameJob $speedFrame -EffectiveDdrMBps 4000 -JobFile (Join-Path $speedPair 'board_4gb_job.txt')
& (Join-Path $PSScriptRoot 'orb_frequency_timing.ps1') -AcceptedLayer (Join-Path $speedPair 'accepted_layer') -AcceptedDescriptor (Join-Path $speedPair 'accepted_descriptor') -FrequencyMHz 150 -FrameJob $speedFrame -ExtendedDiagnostics -JobFile (Join-Path $speedPair 'route_job.txt')
$speedRoute=(Get-Content -LiteralPath (Join-Path $speedPair 'route_job.txt') -Raw).Trim()
& $ProjectPython (Join-Path $PSScriptRoot 'summarize_frequency_result.py') --pair $speedPair --route $speedRoute --frame $speedFrame --protocol $speedProtocol --output (Join-Path $speedPair 'joint_result.json')
if($LASTEXITCODE) {throw 'Joint computer gates failed; bit generation blocked'}
& (Join-Path $PSScriptRoot 'generate_frequency_bit.ps1') -PairJob $speedPair
Write-Output "SPEED150_COMPUTER_REBUILD_COMPLETE=$speedPair"
