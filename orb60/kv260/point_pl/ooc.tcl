set root [file normalize $::env(FPGA_PROJECT_ROOT)]
set job [file normalize $::env(POINT_OOC_JOB)]
set hls [file normalize $::env(POINT_HLS_JOB)]
file mkdir $job
cd $job
set_param general.maxThreads 4
create_project point_ooc [file join $::env(FPGA_VIVADO_BUILD_ROOT) [file tail $job]] -part xck26-sfvc784-2LV-c
set_property ip_repo_paths [list [file join $hls project solution1 impl ip]] [current_project]
update_ip_catalog
create_ip -vlnv xilinx.com:hls:point_project_hls:1.0 -module_name point_ooc
generate_target all [get_ips point_ooc]
synth_ip [get_ips point_ooc]
set f [get_files -all -filter {NAME =~ *point_ooc.dcp}]
if {[llength $f]!=1} {error "Expected one synthesized IP checkpoint: $f"}
open_checkpoint [lindex $f 0]
create_clock -name ap_clk -period 6.666667 [get_ports ap_clk]
opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force [file join $job routed.dcp]
report_utilization -file [file join $job utilization.rpt]
report_utilization -hierarchical -file [file join $job utilization_hierarchical.rpt]
report_timing_summary -report_unconstrained -file [file join $job timing_summary.rpt]
report_route_status -file [file join $job route_status.rpt]
report_drc -file [file join $job drc.rpt]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
if {$wns<0 || $whs<0} {error "OOC timing failed $wns / $whs"}
set f [open [file join $job ooc_pass.json] w]
puts $f "{\"status\":\"OOC_PASS_NOT_SYSTEM\",\"wns_ns\":$wns,\"whs_ns\":$whs}"
close $f
exit
