$ErrorActionPreference = 'Stop'
$ExperimentRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ExperimentRoot '..\..\scripts\project_env.ps1')
& $ProjectPython (Join-Path $PSScriptRoot 'plot_a2_demo.py')
exit $LASTEXITCODE
