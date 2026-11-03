param([Parameter(Mandatory=$true)][string]$Parent,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
& $ProjectPython -m orb60.kv260.point_pl.prepare_tagged --parent $Parent --output $Output
if($LASTEXITCODE){throw 'Parent acceptance or snapshot failed'}
$env:KV260_TAGGED_JOB=[IO.Path]::GetFullPath((Join-Path $ProjectRoot $Output))
$env:FPGA_PROJECT_ROOT=$ProjectRoot
$old=$ErrorActionPreference
try {
    $ErrorActionPreference='Continue'
    & $VivadoBat -mode batch -nojournal -nolog -source (Join-Path $PSScriptRoot 'tagged_export.tcl') *> (Join-Path $env:KV260_TAGGED_JOB 'tagged_export.log')
    $exitCode=$LASTEXITCODE
} finally {$ErrorActionPreference=$old}
if($exitCode){throw 'Tagged bitstream export failed; see retained log'}
& $ProjectPython (Join-Path $env:KV260_TAGGED_JOB 'source_build/check_system.py') $env:KV260_TAGGED_JOB --release *> (Join-Path $env:KV260_TAGGED_JOB 'tagged_check.log')
if($LASTEXITCODE){throw 'Full static/export acceptance failed'}
& $ProjectPython -m orb60.kv260.point_pl.prepare_tagged --output $Output --finalize
if($LASTEXITCODE){throw 'Configuration identity tag check failed'}
