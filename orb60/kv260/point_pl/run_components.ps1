param([Parameter(Mandatory=$true)][string]$Prefix)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
Push-Location $ProjectRoot
try {
    $hlsJob=$Prefix+'_hls';$simJob=$Prefix+'_simlib';$axiJob=$Prefix+'_axi';$oocJob=$Prefix+'_ooc'
    & (Join-Path $PSScriptRoot 'run_hls.ps1') -Job $hlsJob
    $env:FPGA_VIVADO_ROOT=$VivadoRoot;$env:MGLS_LICENSE_FILE=$ModelSimLicense
    & $ProjectPython -m orb60.kv260.point_pl.build_simlib $simJob
    if($LASTEXITCODE){throw 'Vendor simulation models failed'}
    $env:POINT_SIMLIB=Join-Path $ProjectRoot $simJob
    & $ProjectPython -m orb60.kv260.point_pl.run_axi $hlsJob $axiJob *> (Join-Path $ProjectRoot ($axiJob+'_console.log'))
    if($LASTEXITCODE){throw 'Random AXI gate failed'}
    $env:POINT_HLS_JOB=Join-Path $ProjectRoot $hlsJob
    $env:POINT_OOC_JOB=Join-Path $ProjectRoot $oocJob
    New-Item -ItemType Directory -Path $env:POINT_OOC_JOB | Out-Null
    Copy-Item (Join-Path $PSScriptRoot 'ooc.tcl') (Join-Path $env:POINT_OOC_JOB 'source_ooc.tcl')
    $old=$ErrorActionPreference
    try {$ErrorActionPreference='Continue'; & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $env:POINT_OOC_JOB 'source_ooc.tcl') *> (Join-Path $env:POINT_OOC_JOB 'console.log');$code=$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    if($code -or -not(Test-Path (Join-Path $env:POINT_OOC_JOB 'ooc_pass.json'))){throw 'OOC gate failed'}
    Write-Output "Components passed. Hls=$hlsJob Protocol=$axiJob Ooc=$oocJob"
} finally {Pop-Location}
