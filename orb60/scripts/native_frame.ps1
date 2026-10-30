[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$LayerHlsJob,
      [Parameter(Mandatory=$true)][string]$DescriptorHlsJob,
      [Parameter(Mandatory=$true)][string]$BenchmarkJob,
      [Parameter(Mandatory=$true)][string]$ProtocolJob,[switch]$Preflight,[string]$JobFile='')
. (Join-Path $PSScriptRoot 'environment.ps1')
$frameVerilator=(Get-Command verilator -ErrorAction Stop).Source
$frameName='{0}_native_frame_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),([guid]::NewGuid().ToString('N').Substring(0,8))
$frameJob=Join-Path $Orb60Root "build/optimized/gates/$frameName"
$frameTests=Join-Path $frameJob 'inputs/tests'
New-Item -ItemType Directory -Path $frameTests -Force | Out-Null
if($JobFile) {$frameJob | Set-Content -LiteralPath $JobFile -Encoding UTF8}
foreach($frameFile in @('prepare_native_frame.py','native_profile.py','run_native_frame.py','native_frame.cpp','ddr_time.hpp','check_native_harness.py','native_ddr_model_test.cpp')) {
    Copy-Item -LiteralPath (Join-Path $Orb60Root "tests/$frameFile") -Destination $frameTests
}
$frameHashes=Get-ChildItem -LiteralPath (Join-Path $frameJob 'inputs') -Recurse -File | ForEach-Object {
    [ordered]@{Path=$_.FullName.Substring($frameJob.Length+1);SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
}
$frameHashes | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $frameJob 'test_manifest.json') -Encoding UTF8
Write-Output "ORB60_NATIVE_FRAME_JOB=$frameJob PID=$PID"
$ErrorActionPreference='Continue'
$frameArgs=@('--layer',$LayerHlsJob,'--descriptor',$DescriptorHlsJob,'--benchmark',$BenchmarkJob,'--protocol',$ProtocolJob,
    '--verilator',$frameVerilator,'--output',$frameJob,'--parent-pid',$PID)
if($Preflight) {$frameArgs+='--preflight'}
& $ProjectPython (Join-Path $frameTests 'run_native_frame.py') @frameArgs 2>&1 | Tee-Object -FilePath (Join-Path $frameJob 'native.log')
$frameCode=$LASTEXITCODE;$ErrorActionPreference='Stop'
if($frameCode) {throw "Native frame gate failed (exit $frameCode)"}
