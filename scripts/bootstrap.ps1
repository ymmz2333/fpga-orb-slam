param(
    [switch]$SkipInstall,
    [switch]$RequireAmd,
    [switch]$RequireModelSim
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'project_env.ps1')

if (-not (Test-Path -LiteralPath $BasePython)) {
    throw "Python 3.12.12 base runtime was not found: $BasePython"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found on PATH.'
}

if (-not (Test-Path -LiteralPath $ProjectPython)) {
    & uv venv (Join-Path $ProjectRoot '.venv') --python $BasePython
    if ($LASTEXITCODE -ne 0) { throw 'uv failed to create the project virtual environment.' }
}
if (-not $SkipInstall) {
    & uv pip install --python $ProjectPython -r (Join-Path $ProjectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
}

New-Item -ItemType Directory -Force -Path $VivadoBuildRoot | Out-Null
& (Join-Path $PSScriptRoot 'check_environment.ps1') `
    -RequireAmd:$RequireAmd -RequireModelSim:$RequireModelSim

