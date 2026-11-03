set job [file normalize [file dirname [info script]]]
set kernel @KERNEL@
set next [file join $job inputs FPGA_ORB_HLS fastv2 next]
set fast [file join $next ..]
set ref [file join $job inputs FPGA_ORB_SHARED_v1.0]
set flags "-std=c++14 -DFASTV2_HLS_CSIM @FLAGS@ -I[file join $fast include] -I[file join $next include] -I[file join $next hls] -I[file join $job inputs] -I$ref"
cd $job
if {[catch {
    open_project -reset project
    set_top fastv2_${kernel}_hls
    add_files [file join $next src ${kernel}_hls.cpp] -cflags $flags
    add_files -tb [file join $next hls tb_${kernel}_stream.cpp] -cflags $flags
    open_solution -reset solution1 -flow_target vivado
    set_part xck26-sfvc784-2LV-c
    create_clock -period @PERIOD@ -name default
    config_interface -m_axi_addr64=true
    if {$kernel eq "descriptor"} {
        csim_design -clean -O -argv [file join $job descriptor_vectors]
    } else {csim_design -clean -O}
    set f [open [file join $job csim_pass.stamp] w];puts $f "CSIM_PASS";close $f
    csynth_design
    set f [open [file join $job synth_pass.stamp] w];puts $f "SYNTHESIS_COMPLETE_NOT_ROUTE";close $f
    if {$kernel eq "descriptor"} {
        cosim_design -O -rtl verilog -trace_level none -argv [file join $job descriptor_vectors]
    } else {cosim_design -rtl verilog -trace_level none}
    set f [open [file join $job project solution1 sim report fastv2_${kernel}_hls_cosim.rpt] r];set report [read $f];close $f
    if {![regexp {\|[ \t]*Verilog[ \t]*\|[ \t]*Pass[ \t]*\|} $report]} {error "Missing Verilog Pass"}
    export_design -format ip_catalog -rtl verilog
    set f [open [file join $job unit_pass.stamp] w];puts $f "CSIM_SYNTH_COSIM_IP_EXPORT_PASS_NOT_SYSTEM";close $f
} reason]} {puts stderr "KV260_HLS_FAILED: $reason";exit 1}
exit 0
