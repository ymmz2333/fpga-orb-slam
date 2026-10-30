param([string]$Recordings, [string]$Output)
$ErrorActionPreference='Stop'
$ExperimentRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path (Join-Path $ExperimentRoot '../..') 'scripts/project_env.ps1')
if(-not $Recordings) { $Recordings=Join-Path $ProjectRoot 'recordings' }
if(-not $Output) { $Output=Join-Path $ExperimentRoot 'reports/c0' }
$env:PYTHONIOENCODING='utf-8'
& $ProjectPython (Join-Path $PSScriptRoot 'c0_inventory.py') --recordings $Recordings --work (Join-Path $ExperimentRoot 'runtime/c0/source_copy') --output $Output
exit $LASTEXITCODE
