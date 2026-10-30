# Generate a bitstream from an immutable accepted routed checkpoint.
set checkpoint [file normalize $::env(ORB60_BIT_CHECKPOINT)]
set output [file normalize $::env(ORB60_BIT_OUTPUT)]
set checks [file normalize $::env(ORB60_BIT_TIMING_CHECKS)]
set frequency 100
if {[info exists ::env(ORB60_BIT_FREQUENCY)]} {set frequency $::env(ORB60_BIT_FREQUENCY)}
if {$frequency ni {100 125}} {error "Unsupported accepted clock"}
set period [expr {1000.0/$frequency}]
file mkdir $output
set started [clock milliseconds]
open_checkpoint $checkpoint
if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {error "Wrong accepted device"}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Missing actual timing"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Accepted checkpoint timing no longer passes"}
if {abs([get_property REQUIREMENT $setup]-$period)>0.000001} {error "Checkpoint clock differs from the accepted release"}
check_timing -verbose -file [file join $output bit_check_timing.rpt]
source $checks
set f [open [file join $output bit_check_timing.rpt] r];set text [read $f];close $f
next_check_timing_coverage $text
report_route_status -file [file join $output bit_route_status.rpt]
set f [open [file join $output bit_route_status.rpt] r];set text [read $f];close $f
foreach {name pattern} {
    routable {# of routable nets[. \t]*:[ \t]*([0-9]+)}
    routed {# of fully routed nets[. \t]*:[ \t]*([0-9]+)}
    errors {# of nets with routing errors[. \t]*:[ \t]*([0-9]+)}
} {
    if {![regexp $pattern $text unused value]} {error "Missing route count $name"}
    set count($name) $value
}
if {$count(routable)!=$count(routed) || $count(errors)!=0} {error "Checkpoint routing is incomplete"}
report_drc -file [file join $output bit_drc.rpt]
foreach violation [get_drc_violations -quiet] {
    if {[get_property SEVERITY $violation] in {Error {Critical Warning}}} {error "Bitstream DRC failure: $violation"}
}
# Preserve checkpoint configuration. Do not change algorithm, clocks or DRC severity.
write_bitstream -force [file join $output orb60_${frequency}mhz.bit]
set f [open [file join $output bit_metrics.tsv] w]
puts $f "part\t[get_property PART [current_design]]"
puts $f "frequency_mhz\t$frequency"
puts $f "wns_ns\t[get_property SLACK $setup]"
puts $f "whs_ns\t[get_property SLACK $hold]"
puts $f "elapsed_ms\t[expr {[clock milliseconds]-$started}]"
close $f
set f [open [file join $output success.stamp] w];puts $f "ORB60_BITSTREAM_PASS";close $f
puts "ORB60_BITSTREAM_PASS"
exit 0
