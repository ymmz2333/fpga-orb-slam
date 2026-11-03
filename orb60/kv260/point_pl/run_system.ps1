param([Parameter(Mandatory=$true)][string]$Job,[Parameter(Mandatory=$true)][string]$Hls,
      [Parameter(Mandatory=$true)][string]$Protocol,[Parameter(Mandatory=$true)][string]$Ooc)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
& $ProjectPython -m orb60.kv260.point_pl.prepare_system $Job $Hls $Protocol $Ooc
if($LASTEXITCODE){throw 'Unit gates or snapshot failed'}
$env:KV260_DPU_ONLY_JOB=Join-Path $ProjectRoot $Job
$env:KV260_DPU_ONLY_MODE='build';$env:KV260_DPU_MHZ='250';$env:POINT_HLS_JOB=Join-Path $ProjectRoot $Hls
$src=Join-Path $env:KV260_DPU_ONLY_JOB 'source_build'
$old=$ErrorActionPreference
try{$ErrorActionPreference='Continue'; & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $src 'system.tcl') *> (Join-Path $env:KV260_DPU_ONLY_JOB 'console_build.log');$code=$LASTEXITCODE}finally{$ErrorActionPreference=$old}
if($code){throw 'DPU+points implementation failed; reports retained'}
& $ProjectPython (Join-Path $src 'check_system.py') $env:KV260_DPU_ONLY_JOB *> (Join-Path $env:KV260_DPU_ONLY_JOB 'validation_console.log')
if($LASTEXITCODE){throw 'Complete static gate failed; no bitstream exported'}
try{$ErrorActionPreference='Continue'; & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $src 'export.tcl') *> (Join-Path $env:KV260_DPU_ONLY_JOB 'console_export.log');$code=$LASTEXITCODE}finally{$ErrorActionPreference=$old}
if($code){throw 'Bitstream export failed'}
& $ProjectPython (Join-Path $src 'check_system.py') $env:KV260_DPU_ONLY_JOB --release *> (Join-Path $env:KV260_DPU_ONLY_JOB 'release_console.log')
if($LASTEXITCODE){throw 'Artifact acceptance failed'}
Write-Output 'DPU_POINTS_FULL_ROUTE_STATIC_EXPORT_PASS_BOARD_UNTESTED'
