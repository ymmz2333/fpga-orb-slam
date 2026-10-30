set root [file normalize $::env(ORB60_BUNDLE_BIT_JOB)]
set output [file join $root vivado]
open_checkpoint [file join $output next_system_routed.dcp]
set matched 0
foreach clock [get_clocks] {
    if {abs([get_property PERIOD $clock]-1000.0/150)<=0.0005} {set matched 1}
}
if {!$matched} {error "No actual150MHz clock"}
source [file join $root inputs timing_checks.tcl]
source [file join $root inputs route_reports.tcl]
orb60_report_routed [file join $root bit_checks] xc7z015clg485-2 150 fastv2_layer2_hls 1 "Retained ORB-only top rebuilt from bundled paired IP"
write_bitstream -force [file join $output orb60_150mhz.bit]
exit 0
