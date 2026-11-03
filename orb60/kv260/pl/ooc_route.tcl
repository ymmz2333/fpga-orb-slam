# Component-only K26 route. This never produces a board image or full-system claim.
set job [file normalize $::env(KV260_OOC_JOB)]
set kernel $::env(KV260_OOC_KERNEL)
set top fastv2_${kernel}_hls
set source [file normalize $::env(KV260_HLS_JOB)]
if {![file exists [file join $source unit_pass.stamp]]} {error "HLS acceptance missing"}
file mkdir $job
cd $job
create_project -in_memory -part xck26-sfvc784-2LV-c
set_param general.maxThreads 4
foreach path [glob [file join $source project solution1 syn verilog *]] {
    if {[file extension $path] in {.v .sv .dat}} {file copy -force $path [file join $job [file tail $path]]}
}
read_verilog [glob [file join $job *.v]]
foreach path [glob -nocomplain [file join $job *.sv]] {read_verilog -sv $path}
synth_design -top $top -part xck26-sfvc784-2LV-c -mode out_of_context
create_clock -name ap_clk -period 6.666667 [get_ports ap_clk]
write_checkpoint -force synthesized.dcp
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -report_unconstrained -check_timing_verbose -file timing_summary.rpt
report_timing -delay_type max -max_paths 20 -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -file hold_paths.rpt
report_utilization -hierarchical -file utilization_hierarchical.rpt
report_utilization -file utilization.rpt
report_route_status -file route_status.rpt
report_drc -file drc.rpt
check_timing -verbose -file check_timing.rpt
write_checkpoint -force routed.dcp
set setup [get_timing_paths -quiet -delay_type max -max_paths 1]
set hold [get_timing_paths -quiet -delay_type min -max_paths 1]
set wns null;set whs null
if {[llength $setup]} {set wns [get_property SLACK [lindex $setup 0]]}
if {[llength $hold]} {set whs [get_property SLACK [lindex $hold 0]]}
set f [open status.json w]
puts $f "{\"stage\":\"OOC_ROUTED\",\"kernel\":\"$kernel\",\"part\":\"xck26-sfvc784-2LV-c\",\"wns_ns\":$wns,\"whs_ns\":$whs,\"full_system_verified\":false,\"boundary_timing\":\"external AXI timing belongs to unified top\"}"
close $f
exit 0
