param([Parameter(Mandatory=$true)][string]$Job)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$env:POINT_HLS_JOB=Join-Path $ProjectRoot $Job
if(Test-Path $env:POINT_HLS_JOB){throw 'Choose a new HLS job'}
New-Item -ItemType Directory -Path (Join-Path $env:POINT_HLS_JOB 'source') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'point_project.cpp'),(Join-Path $PSScriptRoot 'tb_point_project.cpp'),(Join-Path $PSScriptRoot 'hls.tcl'),$PSCommandPath -Destination (Join-Path $env:POINT_HLS_JOB 'source')
& $ProjectPython -m orb60.kv260.point_pl.vectors (Join-Path $env:POINT_HLS_JOB 'vectors')
if($LASTEXITCODE){throw 'Golden generation failed'}
$old=$ErrorActionPreference
try{$ErrorActionPreference='Continue'; & $VitisHlsBat -f (Join-Path $env:POINT_HLS_JOB 'source/hls.tcl') *> (Join-Path $env:POINT_HLS_JOB 'console.log');$code=$LASTEXITCODE}finally{$ErrorActionPreference=$old}
if($code -or -not(Test-Path (Join-Path $env:POINT_HLS_JOB 'unit_pass.stamp'))){throw 'HLS gate failed; inspect retained log'}
