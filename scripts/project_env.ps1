$ErrorActionPreference = 'Stop'

# Central environment discovery for the D:\pld workspace.  Every build script
# should consume these variables instead of embedding a user profile or tool
# installation path.  Override any default with the documented FPGA_* process
# environment variable; no machine-wide environment changes are made here.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

$localOverride = Join-Path $PSScriptRoot 'local_env.ps1'
if (Test-Path -LiteralPath $localOverride) {
    . $localOverride
}

function Get-FpgaSetting {
    param(
        [Parameter(Mandatory=$true)][string]$EnvironmentName,
        [Parameter(Mandatory=$true)][string]$DefaultValue
    )
    $value = [Environment]::GetEnvironmentVariable($EnvironmentName, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) { return $DefaultValue }
    return $value
}

$VivadoRoot = Get-FpgaSetting 'FPGA_VIVADO_ROOT' 'D:\Xilinx\Vivado\2024.2'
$VitisRoot = Get-FpgaSetting 'FPGA_VITIS_ROOT' 'D:\Xilinx\Vitis\2024.2'
$VitisHlsRoot = Get-FpgaSetting 'FPGA_VITIS_HLS_ROOT' 'D:\Xilinx\Vitis_HLS\2024.2'
$VitisLibrariesRoot = Get-FpgaSetting 'FPGA_VITIS_LIBRARIES_ROOT' `
    'D:\Xilinx\Vitis_Libraries\2024.2_update3'
$ModelSimBin = Get-FpgaSetting 'FPGA_MODELSIM_BIN' 'C:\modeltech64_2020.4\win64'
$ModelSimLicense = Get-FpgaSetting 'FPGA_MODELSIM_LICENSE' `
    (Join-Path $ModelSimBin 'LICENSE.TXT')
$IcarusBin = Get-FpgaSetting 'FPGA_ICARUS_BIN' 'C:\iverilog\bin'
$GtkWaveBin = Get-FpgaSetting 'FPGA_GTKWAVE_BIN' 'C:\iverilog\gtkwave\bin'
$VivadoBuildRoot = Get-FpgaSetting 'FPGA_VIVADO_BUILD_ROOT' `
    (Join-Path $ProjectRoot '.work\vivado')

$VivadoBat = Join-Path $VivadoRoot 'bin\vivado.bat'
$VitisBat = Join-Path $VitisRoot 'bin\vitis.bat'
$VitisHlsBat = Join-Path $VitisHlsRoot 'bin\vitis_hls.bat'
$VitisVisionRoot = Join-Path $VitisLibrariesRoot 'vision'
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$BasePython = Get-FpgaSetting 'FPGA_BASE_PYTHON' `
    'C:\Users\18718\AppData\Roaming\uv\python\cpython-3.12.12-windows-x86_64-none\python.exe'

$prepend = @(
    (Join-Path $VivadoRoot 'bin'),
    (Join-Path $VitisRoot 'bin'),
    (Join-Path $VitisHlsRoot 'bin'),
    $ModelSimBin,
    $IcarusBin,
    $GtkWaveBin,
    (Join-Path $ProjectRoot '.venv\Scripts')
) | Where-Object { Test-Path -LiteralPath $_ }

$existingPath = @($env:PATH -split ';')
$orderedPrepend = [object[]]$prepend.Clone()
[array]::Reverse($orderedPrepend)
foreach ($entry in $orderedPrepend) {
    if ($existingPath -notcontains $entry) {
        $env:PATH = "$entry;$env:PATH"
    }
}

$env:FPGA_PROJECT_ROOT = $ProjectRoot
$env:FPGA_VIVADO_BUILD_ROOT = $VivadoBuildRoot
$env:FPGA_MODELSIM_BIN = $ModelSimBin
$env:FPGA_MODELSIM_LICENSE = $ModelSimLicense
$env:VITIS_VISION_ROOT = $VitisVisionRoot
