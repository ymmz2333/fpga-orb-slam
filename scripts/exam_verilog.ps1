param(
    [ValidateSet('check','compile','sim','wave','gtkwave')][string]$Action='sim',
    [string]$File='', [string]$Top='', [int]$Timeout=30
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
& $ProjectPython (Join-Path $PSScriptRoot 'exam_verilog.py') --action $Action --file $File "--top=$Top" --timeout $Timeout --iverilog (Join-Path $IcarusBin 'iverilog.exe') --vvp (Join-Path $IcarusBin 'vvp.exe') --gtkwave (Join-Path $GtkWaveBin 'gtkwave.exe')
exit $LASTEXITCODE

