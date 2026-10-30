set inputs [file dirname [info script]]
set checkpoint [file normalize $::env(ORB60_ROUTED_CHECKPOINT)]
set output [file normalize $::env(ORB60_RECOVER_REPORTS)]
source [file join $inputs timing_checks.tcl]
set f [open $::env(ORB60_ORIGINAL_TIMING_REPORT) r]
set original [read $f]; close $f
next_check_timing_coverage $original
foreach invalid [list {} [string map {{There are 0 register/latch pins with no clock.} {There are 1 register/latch pins with no clock.}} $original]] {
    if {![catch {next_check_timing_coverage $invalid}]} {error "Timing coverage parser accepted invalid evidence"}
}
puts "ORB60_TIMING_COVERAGE_PARSER_TEST_PASS"
open_checkpoint $checkpoint
if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {error "Routed checkpoint device mismatch"}
set clocks [get_clocks]
if {[llength $clocks] != 1 || abs([get_property PERIOD $clocks] - 10.0) > 0.00001} {error "Recovery requires the actual 100 MHz routed clock"}
source [file join $inputs route_reports.tcl]
set core $::env(ORB60_RECOVER_FRONT_TOP)
if {$core ni {fastv2_front2_hls fastv2_layer2_hls}} {error "Unsupported recovery core"}
orb60_report_routed $output xc7z015clg485-2 100 $core 1 $::env(ORB60_RECOVER_SCOPE)
exit 0
