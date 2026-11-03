# Complete K26 ORB-only candidate for PS CPU MiDaS. No board programming.
set root [file normalize $::env(FPGA_PROJECT_ROOT)]
set job [file normalize $::env(KV260_ORB_ONLY_JOB)]
set scratch [file normalize $::env(FPGA_VIVADO_BUILD_ROOT)]
set project_dir [file join $scratch [file tail $job]]
set_param general.maxThreads 4
file mkdir $job
cd $job
proc wire {src args} {
    set pins [list [get_bd_pins $src]]
    foreach dst $args {lappend pins [get_bd_pins $dst]}
    connect_bd_net {*}$pins
}
proc axi {a b} {connect_bd_intf_net [get_bd_intf_pins $a] [get_bd_intf_pins $b]}
set layer [file join $root orb60 build kv260_system hls_layer2_150_20261102]
set descriptor [file join $root orb60 build kv260_system hls_descriptor_150_20261102]
foreach path [list $layer $descriptor] {
    if {![file exists [file join $path unit_pass.stamp]]} {error "Accepted HLS core required: $path"}
}
create_project kv260_orb_only $project_dir -part xck26-sfvc784-2LV-c
set_property board_part xilinx.com:kv260_som:part0:1.4 [current_project]
set_property ip_repo_paths [list [file join $layer project solution1 impl ip] [file join $descriptor project solution1 impl ip]] [current_project]
update_ip_catalog
create_bd_design system
create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} [get_bd_cells ps]
set_property -dict [list CONFIG.PSU__USE__M_AXI_GP0 1 CONFIG.PSU__USE__M_AXI_GP1 0 CONFIG.PSU__USE__M_AXI_GP2 0 \
    CONFIG.PSU__USE__S_AXI_GP0 0 CONFIG.PSU__USE__S_AXI_GP1 0 CONFIG.PSU__USE__S_AXI_GP2 0 \
    CONFIG.PSU__USE__S_AXI_GP3 0 CONFIG.PSU__USE__S_AXI_GP4 1 CONFIG.PSU__USE__S_AXI_GP5 1 \
    CONFIG.PSU__USE__S_AXI_GP6 0 CONFIG.PSU__USE__IRQ0 1 CONFIG.PSU__FPGA_PL0_ENABLE 1 \
    CONFIG.PSU__FPGA_PL1_ENABLE 0 CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ 100] [get_bd_cells ps]
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clocks
set ref_mhz [expr {[get_property CONFIG.FREQ_HZ [get_bd_pins ps/pl_clk0]] / 1000000.0}]
set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ $ref_mhz CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 150 CONFIG.RESET_TYPE ACTIVE_LOW] [get_bd_cells clocks]
wire ps/pl_clk0 clocks/clk_in1
wire ps/pl_resetn0 clocks/resetn
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset_orb
wire clocks/clk_out1 reset_orb/slowest_sync_clk ps/maxihpm0_fpd_aclk ps/saxihp2_fpd_aclk ps/saxihp3_fpd_aclk
wire ps/pl_resetn0 reset_orb/ext_reset_in
wire clocks/locked reset_orb/dcm_locked
foreach {name vlnv} {layer xilinx.com:hls:fastv2_layer2_hls:1.0 descriptor xilinx.com:hls:fastv2_descriptor_hls:1.0} {
    create_bd_cell -type ip -vlnv $vlnv $name
    wire clocks/clk_out1 $name/ap_clk
    wire reset_orb/peripheral_aresetn $name/ap_rst_n
}
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dwidth_converter:2.1 control_width
set_property -dict [list CONFIG.SI_DATA_WIDTH 128 CONFIG.MI_DATA_WIDTH 32] [get_bd_cells control_width]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter:2.1 control_protocol
set_property -dict [list CONFIG.SI_PROTOCOL AXI4 CONFIG.MI_PROTOCOL AXI4LITE CONFIG.DATA_WIDTH 32] [get_bd_cells control_protocol]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 control
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 2] [get_bd_cells control]
wire clocks/clk_out1 control_width/s_axi_aclk control_protocol/aclk control/ACLK control/S00_ACLK control/M00_ACLK control/M01_ACLK
wire reset_orb/interconnect_aresetn control_width/s_axi_aresetn control_protocol/aresetn control/ARESETN control/S00_ARESETN control/M00_ARESETN control/M01_ARESETN
axi ps/M_AXI_HPM0_FPD control_width/S_AXI
axi control_width/M_AXI control_protocol/S_AXI
axi control_protocol/M_AXI control/S00_AXI
axi control/M00_AXI layer/s_axi_control
axi control/M01_AXI descriptor/s_axi_control
foreach {name hp sources} {
    orb_mem0 HP2 {layer/m_axi_gmem0 layer/m_axi_gmem2 descriptor/m_axi_gmem0 descriptor/m_axi_gmem1}
    orb_mem1 HP3 {layer/m_axi_gmem1 layer/m_axi_gmem3 descriptor/m_axi_gmem2 descriptor/m_axi_gmem3}
} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 $name
    set_property -dict [list CONFIG.NUM_SI 4 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells $name]
    wire clocks/clk_out1 $name/aclk
    wire reset_orb/interconnect_aresetn $name/aresetn
    set i 0
    foreach source $sources {axi $source [format {%s/S%02d_AXI} $name $i];incr i}
    axi $name/M00_AXI ps/S_AXI_${hp}_FPD
}
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 interrupts
set_property CONFIG.NUM_PORTS 2 [get_bd_cells interrupts]
wire layer/interrupt interrupts/In0
wire descriptor/interrupt interrupts/In1
wire interrupts/dout ps/pl_ps_irq0
assign_bd_address -offset 0xA0000000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs layer/s_axi_control/Reg]
assign_bd_address -offset 0xA0010000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs descriptor/s_axi_control/Reg]
assign_bd_address
validate_bd_design
save_bd_design
write_bd_tcl -force [file join $job system_generated.tcl]
set f [open [file join $job address_map.tsv] w]
foreach seg [get_bd_addr_segs -hierarchical] {
    if {[get_property -quiet OFFSET $seg] ne ""} {puts $f "$seg\t[get_property OFFSET $seg]\t[get_property RANGE $seg]"}
}
close $f
set bd [get_files system.bd]
set_property synth_checkpoint_mode None $bd
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
set f [open [file join $job project_path.txt] w];puts $f [file join $project_dir kv260_orb_only.xpr];close $f
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "ORB-only synthesis failed"}
set_property strategy Performance_Explore [get_runs impl_1]
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "ORB-only implementation failed"}
open_run impl_1
write_checkpoint -force [file join $job routed.dcp]
report_utilization -file [file join $job utilization.rpt]
report_utilization -hierarchical -file [file join $job utilization_hierarchical.rpt]
report_route_status -file [file join $job route_status.rpt]
report_design_analysis -congestion -file [file join $job congestion.rpt]
report_timing_summary -check_timing_verbose -report_unconstrained -file [file join $job timing_summary.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $job setup_paths.rpt]
report_timing -delay_type min -max_paths 20 -file [file join $job hold_paths.rpt]
report_drc -file [file join $job drc.rpt]
report_methodology -file [file join $job methodology.rpt]
report_cdc -details -file [file join $job cdc.rpt]
check_timing -verbose -file [file join $job check_timing.rpt]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == {Critical Warning}}]
set setup [get_timing_paths -quiet -delay_type max -slack_lesser_than 0 -max_paths 1]
set hold [get_timing_paths -quiet -delay_type min -slack_lesser_than 0 -max_paths 1]
if {[llength $errors] || [llength $setup] || [llength $hold]} {error "ORB-only static acceptance failed; reports retained"}
write_hw_platform -fixed -force -file [file join $job kv260_orb_only.xsa]
puts "KV260_ORB_ONLY_ROUTED_REPORTS_COMPLETE_NOT_BOARD_VERIFIED"
exit
