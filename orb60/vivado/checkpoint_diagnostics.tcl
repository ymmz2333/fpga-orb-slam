set checkpoint [file normalize $::env(ORB60_DIAGNOSTIC_CHECKPOINT)]
set output [file normalize $::env(ORB60_DIAGNOSTIC_REPORTS)]
source [file join [file dirname [info script]] diagnostic_reports.tcl]
if {[catch {
    set_param general.maxThreads 4
    open_checkpoint $checkpoint
    if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {error "Wrong diagnostic checkpoint part"}
    set clock [get_clocks clk_fpga_0]
    if {[llength $clock] != 1 || abs([get_property PERIOD $clock]-10.0)>0.000001} {error "Wrong diagnostic clock"}
    orb60_diagnostic_reports $output
    set f [open [file join $output success.stamp] w];puts $f "READ_ONLY_DIAGNOSTIC_EXPORT";close $f
    close_design
} problem options]} {
    puts stderr "ORB60_DIAGNOSTIC_FAILED: $problem"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
