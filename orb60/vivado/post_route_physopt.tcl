# Bounded physical optimization of a separate copy of the completed 125 MHz top.
# Algorithm RTL, parent checkpoint and clock constraints are not edited.
set inputs [file dirname [info script]]
set checkpoint [file normalize $::env(ORB60_PHYSOPT_CHECKPOINT)]
set output [file normalize $::env(ORB60_PHYSOPT_REPORTS)]
set directive $::env(ORB60_PHYSOPT_DIRECTIVE)
if {$directive ni {AggressiveExplore Explore}} {error "Unsupported bounded physical directive"}
source [file join $inputs timing_checks.tcl]
source [file join $inputs route_reports.tcl]
file mkdir $output
set_param general.maxThreads $::env(ORB60_PHYSOPT_THREADS)
open_checkpoint $checkpoint
if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {
    error "Physical optimization checkpoint device mismatch"
}
proc orb60_check_125_clock {} {
    set clocks [get_clocks]
    if {[llength $clocks] != 1 || [get_property NAME $clocks] ne "clk_fpga_0" ||
        abs([get_property PERIOD $clocks] - 8.0) > 0.00001} {
        error "Physical optimization requires the actual unchanged 8 ns clock"
    }
    return [get_property NAME $clocks]
}
orb60_check_125_clock
set before_path [get_timing_paths -delay_type max -max_paths 1]
if {[llength $before_path] != 1 ||
    abs([get_property SLACK $before_path] - $::env(ORB60_PHYSOPT_PARENT_WNS)) > 0.0011} {
    error "Parent checkpoint does not match retained routed timing"
}
check_timing -verbose -file [file join $output input_check_timing.rpt]
set report_file [open [file join $output input_check_timing.rpt] r]
set coverage [read $report_file]; close $report_file
next_check_timing_coverage $coverage
report_timing_summary -check_timing_verbose -report_unconstrained -file [file join $output input_timing.rpt]
write_xdc -force [file join $output input_constraints.xdc]
set progress [open [file join $output physical_optimization.tsv] w]
puts $progress "directive\t$directive"
puts $progress "before_wns_ns\t[get_property SLACK $before_path]"
puts $progress "before_endpoint\t[get_property ENDPOINT_PIN $before_path]"
flush $progress
puts "ORB60_PHYSOPT_BEGIN WNS=[get_property SLACK $before_path]"
set began [clock milliseconds]
phys_opt_design -directive $directive
puts $progress "optimization_elapsed_ms\t[expr {[clock milliseconds] - $began}]"
orb60_check_125_clock
set after_path [get_timing_paths -delay_type max -max_paths 1]
puts $progress "after_wns_ns\t[get_property SLACK $after_path]"
close $progress
set clocks_file [open [file join $output post_route_clocks.tsv] w]
puts $clocks_file "clk_fpga_0\t8.000"
close $clocks_file
write_xdc -force [file join $output post_constraints.xdc]
# This exports a new complete checkpoint and all evidence before its strict
# setup/hold/route/coverage/DRC acceptance. Negative slack remains a real FAIL.
orb60_report_routed $output xc7z015clg485-2 125 fastv2_layer2_hls 1 \
    "Complete 8 ns HLS layer + A32 descriptor top after $directive; candidate protocol/frame/board gates pending"
exit 0
