param([switch]$BuildOnly)
$ErrorActionPreference='Stop'
$ExperimentRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ExperimentRoot '..\..\scripts\project_env.ps1')
& $ProjectPython (Join-Path $PSScriptRoot 'build_intrinsics_preview.py')
if ($LASTEXITCODE -ne 0) { throw 'Preview generation failed' }
$PreviewPath=Join-Path $ExperimentRoot 'runtime\c\visual_checks\provisional_intrinsics\index.html'
if (-not $BuildOnly) { Invoke-Item -LiteralPath $PreviewPath }
Write-Output $PreviewPath
