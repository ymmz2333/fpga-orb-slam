set fastv2_root [file normalize [file join [file dirname [info script]] ..]]
set project_root [file normalize [file join $fastv2_root ..]]
set reference_root [file normalize [file join $project_root .. FPGA_ORB_SHARED_v1.0]]
set source_file [file join $fastv2_root src fastv2_hls.cpp]
set include_flags "-std=c++0x -DFASTV2_HLS_CSIM -I[file join $fastv2_root include] -I$reference_root"
set selection front
if {[info exists ::env(FASTV2_HLS_SELECTION)]} {
    set selection $::env(FASTV2_HLS_SELECTION)
}
if {$selection ne "front" && $selection ne "resize"} {
    puts stderr "FASTV2_HLS_FAILED: unsupported selection $selection"
    exit 1
}
if {[info exists ::env(FASTV2_HLS_COSIM)] && $::env(FASTV2_HLS_COSIM) eq "1"} {
    append include_flags " -DFASTV2_HLS_COSIM_SMALL_DEPTH"
}
set build_root [file join $fastv2_root hls_build]
file mkdir $build_root
cd $build_root

if {[catch {
    set project_name fastv2_$selection
    if {[info exists ::env(FASTV2_HLS_COSIM)] && $::env(FASTV2_HLS_COSIM) eq "1"} {
        set project_name fastv2_${selection}_cosim
    }
    open_project -reset $project_name
    if {$selection eq "front"} {
        set_top fastv2_front_hls
        set testbench [file join $fastv2_root hls tb_fastv2.cpp]
    } else {
        set_top fastv2_resize_hls
        set testbench [file join $fastv2_root hls tb_resize.cpp]
    }
    add_files $source_file -cflags $include_flags
    add_files -tb $testbench -cflags $include_flags
    open_solution -reset solution1
    set_part {xc7z015clg485-2}
    create_clock -period 10 -name default
    csim_design -clean
    csynth_design
    if {[info exists ::env(FASTV2_HLS_COSIM)] && $::env(FASTV2_HLS_COSIM) eq "1"} {
        cosim_design -rtl verilog -trace_level none
    }
    close_project
} failure]} {
    puts stderr "FASTV2_HLS_FAILED: $failure"
    exit 1
}
if {[info exists ::env(FASTV2_HLS_SUCCESS_STAMP)]} {
    set stamp [open $::env(FASTV2_HLS_SUCCESS_STAMP) w]
    puts $stamp "FASTV2_HLS_SUCCESS"
    close $stamp
}
exit 0
