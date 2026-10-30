set fastv2_root [file normalize [file join [file dirname [info script]] ..]]
set build_root [file join $fastv2_root hls_build]
cd $build_root

# @brief Verify the existing synthesized fastv2 RTL against frozen signatures.
if {[catch {
    set selection front
    if {[info exists ::env(FASTV2_HLS_SELECTION)]} {
        set selection $::env(FASTV2_HLS_SELECTION)
    }
    if {$selection ne "front" && $selection ne "resize"} {
        error "Unsupported fastv2 co-simulation selection $selection"
    }
    open_project fastv2_${selection}_cosim
    open_solution solution1
    cosim_design -rtl verilog -trace_level none
    close_project
} failure]} {
    puts stderr "FASTV2_COSIM_FAILED: $failure"
    exit 1
}
if {[info exists ::env(FASTV2_HLS_SUCCESS_STAMP)]} {
    set stamp [open $::env(FASTV2_HLS_SUCCESS_STAMP) w]
    puts $stamp "FASTV2_COSIM_SUCCESS"
    close $stamp
}
exit 0
