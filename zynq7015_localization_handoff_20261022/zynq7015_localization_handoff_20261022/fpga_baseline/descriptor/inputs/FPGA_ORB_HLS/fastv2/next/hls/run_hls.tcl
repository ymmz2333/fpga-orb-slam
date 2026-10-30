# Isolated next-revision HLS flow. A unique job directory owns every output.
set next_root [file normalize [file join [file dirname [info script]] ..]]
if {[info exists ::env(NEXT_HLS_AUTHOR_ROOT)]} {
    set next_root [file normalize $::env(NEXT_HLS_AUTHOR_ROOT)]
}
set source_root $next_root
if {[info exists ::env(NEXT_HLS_SOURCE_ROOT)]} {
    set source_root [file normalize $::env(NEXT_HLS_SOURCE_ROOT)]
}
set fastv2_root [file normalize [file join $source_root ..]]
set project_root [file normalize [file join $fastv2_root ..]]
set reference_root [file normalize [file join $project_root .. FPGA_ORB_SHARED_v1.0]]
set selection all
if {[info exists ::env(NEXT_HLS_SELECTION)]} {
    set selection $::env(NEXT_HLS_SELECTION)
}
if {$selection ni {all front resize gaussian image}} {
    puts stderr "NEXT_HLS_FAILED: unsupported selection $selection"
    exit 1
}
if {![info exists ::env(NEXT_HLS_BUILD_ROOT)] || ![info exists ::env(NEXT_HLS_SUCCESS_STAMP)]} {
    puts stderr "NEXT_HLS_FAILED: use next/scripts/synthesize.ps1 to select an isolated job directory"
    exit 1
}
set build_root [file normalize $::env(NEXT_HLS_BUILD_ROOT)]
# Reject an output path outside the authored next revision's generated subtree.
set allowed_root [file normalize [file join $next_root hls_build]]
if {![string equal -nocase [string range $build_root 0 [string length $allowed_root]] "$allowed_root/"]} {
    puts stderr "NEXT_HLS_FAILED: output directory must be below $allowed_root"
    exit 1
}
file mkdir $build_root
cd $build_root
set flags "-std=c++0x -DFASTV2_HLS_CSIM -I[file join $fastv2_root include] -I[file join $source_root include] -I[file join $source_root hls] -I[file join $source_root host_build generated] -I$reference_root"
set kernels [list $selection]
if {$selection eq "all"} { set kernels {resize front gaussian} }
if {$selection eq "image"} { set kernels {resize gaussian} }
set csim_only [expr {[info exists ::env(NEXT_HLS_CSIM_ONLY)] && $::env(NEXT_HLS_CSIM_ONLY) eq "1"}]
set cosim [expr {[info exists ::env(NEXT_HLS_COSIM)] && $::env(NEXT_HLS_COSIM) eq "1"}]
if {$cosim && $csim_only} { puts stderr "NEXT_HLS_FAILED: incompatible simulation options"; exit 1 }

if {[catch {
    foreach kernel $kernels {
        puts "NEXT_STAGE_BEGIN kernel=$kernel time=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S}]"
        open_project next_$kernel
        if {$kernel eq "gaussian"} {
            set_top fastv2_gaussian_hls
            add_files [file join $source_root src gaussian_hls.cpp] -cflags $flags
            add_files -tb [file join $source_root hls tb_gaussian_stream.cpp] -cflags $flags
        } else {
            set_top fastv2_${kernel}_hls
            set kernel_source fastv2_hls.cpp
            if {$kernel eq "resize"} { set kernel_source resize_hls.cpp }
            add_files [file join $source_root src $kernel_source] -cflags $flags
            if {$kernel eq "front"} {
                add_files -tb [file join $source_root hls tb_front_stream.cpp] -cflags $flags
            } else {
                add_files -tb [file join $source_root hls tb_resize_stream.cpp] -cflags $flags
            }
        }
        open_solution solution1
        set_part {xc7z015clg485-2}
        create_clock -period 10 -name default
        csim_design -clean
        if {!$csim_only} { csynth_design }
        if {$cosim} {
            cosim_design -rtl verilog -trace_level none
            set report_path [file join $build_root next_$kernel solution1 sim report fastv2_${kernel}_hls_cosim.rpt]
            if {![file exists $report_path]} { error "Missing RTL result report for $kernel" }
            set report_file [open $report_path r]
            set report_text [read $report_file]
            close $report_file
            if {![regexp {\|[ \t]*Verilog[ \t]*\|[ \t]*Pass[ \t]*\|} $report_text]} {
                error "RTL report does not contain Verilog Pass for $kernel"
            }
        }
        close_project
        set stage_stamp [open [file join $build_root ${kernel}.success] w]
        puts $stage_stamp "NEXT_STAGE_SUCCESS kernel=$kernel csim_only=$csim_only cosim=$cosim"
        close $stage_stamp
        puts "NEXT_STAGE_DONE kernel=$kernel"
    }
} failure]} {
    puts stderr "NEXT_HLS_FAILED: $failure"
    exit 1
}
set stamp [open $::env(NEXT_HLS_SUCCESS_STAMP) w]
puts $stamp "NEXT_HLS_SUCCESS selection=$selection csim_only=$csim_only cosim=$cosim"
close $stamp
exit 0
