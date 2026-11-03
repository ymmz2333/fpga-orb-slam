param([Parameter(Mandatory=$true)][string]$Job)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../../scripts/project_env.ps1')
$jobPath=Join-Path $ProjectRoot $Job
& $ProjectPython (Join-Path $PSScriptRoot 'check_dpu_only.py') $jobPath --release
if ($LASTEXITCODE -ne 0) { throw 'Full static and artifact checks must pass before opening the retained final platform' }
& $VivadoBat -mode gui -source (Join-Path $PSScriptRoot 'open_dpu_only.tcl') -tclargs $jobPath
