# Bit only from a hash-paired150MHz routed checkpoint. No design modifications.
set checkpoint [file normalize $::env(ORB60_BIT_CHECKPOINT)]
set output [file normalize $::env(ORB60_BIT_OUTPUT)]
open_checkpoint $checkpoint
if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {error "Wrong device"}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]==0 || [llength $hold]==0} {error "Missing actual timing"}
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Actual setup/hold fails"}
set matched 0
foreach core_clock [get_clocks] {
    if {abs([get_property PERIOD $core_clock]-1000.0/150)<=0.0005} {set matched 1}
}
if {!$matched} {error "No actual150MHz clock"}
check_timing -verbose -file [file join $output bit_check_timing.rpt]
source $::env(ORB60_BIT_TIMING_CHECKS)
set f [open [file join $output bit_check_timing.rpt] r];set text [read $f];close $f
next_check_timing_coverage $text
report_route_status -file [file join $output bit_route_status.rpt]
set f [open [file join $output bit_route_status.rpt] r];set text [read $f];close $f
foreach {name pattern} {
    routable {# of routable nets[. \t]*:[ \t]*([0-9]+)}
    routed {# of fully routed nets[. \t]*:[ \t]*([0-9]+)}
    errors {# of nets with routing errors[. \t]*:[ \t]*([0-9]+)}
} {
    if {![regexp $pattern $text unused value]} {error "Missing route count$name"}
    set count($name) $value
}
if {$count(routable)!=$count(routed) || $count(errors)!=0} {error "Incomplete routing"}
report_drc -file [file join $output bit_drc.rpt]
foreach violation [get_drc_violations -quiet] {
    if {[get_property SEVERITY $violation] in {Error {Critical Warning}}} {error "Bit DRC failure:$violation"}
}
write_bitstream -force [file join $output orb60_150mhz.bit]
set f [open [file join $output success.stamp] w];puts $f "ORB60_FREQUENCY_BIT_PASS";close $f
puts "ORB60_FREQUENCY_BIT_PASS"
exit 0
