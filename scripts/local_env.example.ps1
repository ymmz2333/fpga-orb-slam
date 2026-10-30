# Copy this file to scripts/local_env.ps1 only when this machine uses paths
# different from the defaults in project_env.ps1.  local_env.ps1 is ignored.
$env:FPGA_VIVADO_ROOT = 'D:\Xilinx\Vivado\2024.2'
$env:FPGA_VITIS_ROOT = 'D:\Xilinx\Vitis\2024.2'
$env:FPGA_VITIS_HLS_ROOT = 'D:\Xilinx\Vitis_HLS\2024.2'
$env:FPGA_VITIS_LIBRARIES_ROOT = 'D:\Xilinx\Vitis_Libraries\2024.2_update3'
$env:FPGA_MODELSIM_BIN = 'C:\modeltech64_2020.4\win64'
$env:FPGA_MODELSIM_LICENSE = 'C:\modeltech64_2020.4\win64\LICENSE.TXT'
$env:FPGA_ICARUS_BIN = 'C:\iverilog\bin'
$env:FPGA_GTKWAVE_BIN = 'C:\iverilog\gtkwave\bin'
$env:FPGA_BASE_PYTHON = `
    'C:\Users\18718\AppData\Roaming\uv\python\cpython-3.12.12-windows-x86_64-none\python.exe'
$env:FPGA_VIVADO_BUILD_ROOT = 'D:\pld\.work\vivado'

