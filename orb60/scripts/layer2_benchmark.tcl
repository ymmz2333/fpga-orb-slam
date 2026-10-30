set job [file normalize $::env(ORB60_BENCH_JOB)]
set next [file join $job inputs FPGA_ORB_HLS fastv2 next]
set fast [file join $next ..]
set flags "-std=c++14 -DFASTV2_HLS_CSIM -I[file join $fast include] -I[file join $next include] -I[file join $next hls]"
cd [file join $job projects]
if {[catch {
    open_project layer2
    # Project management only. Reuse the accepted synthesis/RTL unchanged.
    # Keep the design entry and synthesis metadata intact; replace only the TB.
    remove_files [file join $::env(ORB60_BENCH_PARENT) inputs FPGA_ORB_HLS fastv2 next hls tb_layer2_stream.cpp]
    add_files -tb [file join $job inputs tb_layer2_benchmark.cpp] -cflags $flags
    open_solution solution1
    csim_design -clean -O -argv [file join $job vectors]
    cosim_design -O -rtl verilog -trace_level none -argv [file join $job vectors]
    set path [file join $job projects layer2 solution1 sim report fastv2_layer2_hls_cosim.rpt]
    set f [open $path r]; set report [read $f]; close $f
    if {![regexp {\|[ \t]*Verilog[ \t]*\|[ \t]*Pass[ \t]*\|} $report]} {error "Missing Verilog Pass"}
    close_project
} failure]} {puts stderr "ORB60_BENCH_FAILED: $failure"; exit 1}
set f [open [file join $job success.stamp] w]; puts $f "ORB60_LAYER2_BENCH_SUCCESS"; close $f
exit 0
