param([Parameter(Mandatory=$true)][string]$Controller)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/project_env.ps1')
& $ProjectPython (Join-Path $PSScriptRoot '../viewer/app.py') --demo-controller $Controller
exit $LASTEXITCODE
