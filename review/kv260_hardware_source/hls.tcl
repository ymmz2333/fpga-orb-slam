set job [file normalize $::env(POINT_HLS_JOB)]
cd $job
if {[catch {
    open_project -reset project
    set_top point_project_hls
    add_files [file join $job source point_project.cpp] -cflags {-std=c++14}
    add_files -tb [file join $job source tb_point_project.cpp] -cflags {-std=c++14}
    open_solution -reset solution1 -flow_target vivado
    set_part xck26-sfvc784-2LV-c
    create_clock -period 6.666667 -name default
    config_interface -m_axi_addr64=true
    csim_design -clean -O -argv "[file join $job vectors] all"
    csynth_design
    cosim_design -rtl verilog -trace_level none -argv "[file join $job vectors] small"
    set f [open [file join $job project solution1 sim report point_project_hls_cosim.rpt] r];set r [read $f];close $f
    if {![regexp {\|[ \t]*Verilog[ \t]*\|[ \t]*Pass[ \t]*\|} $r]} {error "Verilog cosim not passed"}
    export_design -format ip_catalog -rtl verilog
    set f [open [file join $job unit_pass.stamp] w];puts $f "CSIM_SYNTH_COSIM_PASS_NOT_PROTOCOL_OR_BOARD";close $f
} reason]} {puts stderr $reason;exit 1}
exit 0
