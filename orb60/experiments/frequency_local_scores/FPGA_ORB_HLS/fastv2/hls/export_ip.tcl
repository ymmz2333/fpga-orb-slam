set fastv2_root [file normalize [file join [file dirname [info script]] ..]]
set build_root [file join $fastv2_root hls_build]
cd $build_root

# @brief Export one synthesized fastv2 solution as a Vivado IP component.
# @param name HLS project directory below fastv2/hls_build.
proc export_fastv2_ip {name} {
    open_project $name
    open_solution solution1
    export_design -rtl verilog -format ip_catalog
    close_project
}

if {[catch {
    set selection both
    if {[info exists ::env(FASTV2_HLS_SELECTION)]} {
        set selection $::env(FASTV2_HLS_SELECTION)
    }
    if {$selection eq "both" || $selection eq "front"} {
        export_fastv2_ip fastv2_front
    }
    if {$selection eq "both" || $selection eq "resize"} {
        export_fastv2_ip fastv2_resize
    }
} failure]} {
    puts stderr "FASTV2_EXPORT_FAILED: $failure"
    exit 1
}
if {[info exists ::env(FASTV2_HLS_SUCCESS_STAMP)]} {
    set stamp [open $::env(FASTV2_HLS_SUCCESS_STAMP) w]
    puts $stamp "FASTV2_EXPORT_SUCCESS"
    close $stamp
}
exit 0
