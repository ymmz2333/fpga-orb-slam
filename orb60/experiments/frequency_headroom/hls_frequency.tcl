set job [file normalize $::env(ORB60_HLS_JOB)]
set next [file join $job inputs FPGA_ORB_HLS fastv2 next]
set fast [file join $next ..]
set ref [file join $job inputs FPGA_ORB_SHARED_v1.0]
set flags "-std=c++14 -DFASTV2_HLS_CSIM -I[file join $fast include] -I[file join $next include] -I[file join $next hls] -I[file join $job inputs] -I$ref"
if {[info exists ::env(ORB60_DESCRIPTOR_WIDTH_MODE)]} {
    append flags " -DORB60_DESCRIPTOR_WIDTH_MODE=$::env(ORB60_DESCRIPTOR_WIDTH_MODE)"
}
if {[info exists ::env(ORB60_DESCRIPTOR_PREFETCH)]} {
    append flags " -DORB60_DESCRIPTOR_PREFETCH=$::env(ORB60_DESCRIPTOR_PREFETCH)"
}
foreach macro {ORB60_DESCRIPTOR_PATCH32 ORB60_DESCRIPTOR_MOMENT_FUSION ORB60_DESCRIPTOR_FAST_QUANTIZE ORB60_SLICE_COMPACT_MODE ORB60_LAYER_PPC ORB60_FAST_STAGED ORB60_LAYER_IO_OVERLAP ORB60_LAYER_BRAM_FIFOS} {
    if {[info exists ::env($macro)]} {append flags " -D$macro=$::env($macro)"}
}
file mkdir [file join $job projects]
cd [file join $job projects]
set selection $::env(ORB60_HLS_KERNEL)
set kernels [list $selection]
if {$selection eq "all"} {set kernels {front resize gaussian}}
if {[catch {
    foreach kernel $kernels {
        puts "ORB60_STAGE_BEGIN kernel=$kernel"
        open_project -reset $kernel
        set top fastv2_${kernel}_hls
        set testbench tb_${kernel}_stream.cpp
        if {$kernel eq "front" && [file exists [file join $next hls tb_front64_stream.cpp]]} {
            set top fastv2_front64_hls
            set testbench tb_front64_stream.cpp
        }
        set_top $top
        set source ${kernel}_hls.cpp
        if {$kernel eq "front"} {set source fastv2_hls.cpp}
        add_files [file join $next src $source] -cflags $flags
        add_files -tb [file join $next hls $testbench] -cflags $flags
        open_solution -reset solution1 -flow_target vivado
        set_part xc7z015clg485-2
        create_clock -period $::env(ORB60_HLS_PERIOD) -name default
        config_interface -m_axi_addr64=false
        if {$kernel eq "merge4"} {config_rtl -reset_level low}
        if {$kernel eq "descriptor"} {
            csim_design -clean -O -argv [file join $job descriptor_vectors]
        } else {csim_design -clean}
        if {!$::env(ORB60_HLS_CSIM_ONLY)} {
            csynth_design
            if {$::env(ORB60_HLS_COSIM)} {
                if {$kernel eq "descriptor"} {
                    cosim_design -O -rtl verilog -trace_level none -argv [file join $job descriptor_vectors]
                } else {cosim_design -rtl verilog -trace_level none}
                set path [file join $job projects $kernel solution1 sim report ${top}_cosim.rpt]
                set f [open $path r]; set report [read $f]; close $f
                if {![regexp {\|[ \t]*Verilog[ \t]*\|[ \t]*Pass[ \t]*\|} $report]} {error "Missing Verilog Pass for $kernel"}
            }
            if {![info exists ::env(ORB60_HLS_NO_EXPORT)] || !$::env(ORB60_HLS_NO_EXPORT)} {
                export_design -format ip_catalog -rtl verilog
            }
        }
        close_project
        puts "ORB60_STAGE_DONE kernel=$kernel"
    }
} failure]} {puts stderr "ORB60_HLS_FAILED: $failure"; exit 1}
set f [open [file join $job success.stamp] w]; puts $f "ORB60_HLS_SUCCESS"; close $f
exit 0
