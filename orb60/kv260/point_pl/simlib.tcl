# Retained diagnostic attempt: this catalog selection found no valid libraries.
# It is NOT an acceptance/build entry. Use build_simlib.py, whose unchanged
# vendor models actually passed the randomized RTL tests.
set path [file normalize $::env(POINT_SIMLIB)]
file mkdir $path
compile_simlib -simulator modelsim -simulator_exec_path [string map {\\ /} $::env(FPGA_MODELSIM_BIN)] \
    -directory $path -family zynquplus -library all -ip floating_point -language all -no_systemc_compile -verbose
exit
