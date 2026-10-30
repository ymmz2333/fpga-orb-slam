param([string]$Compiler=$env:FPGA_NATIVE_CXX)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../../scripts/project_env.ps1')
if ($Compiler) {
 & $ProjectPython -m orb60.demo_bridge.build_native --compiler $Compiler
 if ($LASTEXITCODE) {exit $LASTEXITCODE}
}
Push-Location $ProjectRoot
try { & $ProjectPython -m orb60.demo_bridge.verify; exit $LASTEXITCODE }
finally {Pop-Location}
