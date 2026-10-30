param([Parameter(Mandatory=$true)][string]$Zip,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')
& $ProjectPython (Join-Path $PSScriptRoot 'exam_import.py') $Zip $Destination
exit $LASTEXITCODE
