set path [file normalize $::env(POINT_SIMLIB)]
file mkdir $path
compile_simlib -simulator modelsim -simulator_exec_path [string map {\\ /} $::env(FPGA_MODELSIM_BIN)] \
    -directory $path -family zynquplus -library all -ip floating_point -language all -no_systemc_compile -verbose
exit
