# Shared-read 2PPC layer with AMD PS7/AXI/reset, 100 MHz timing experiment.
set root [file normalize $::env(ORB60_LAYER_TIMING_ROOT)]
set inputs [file join $root inputs]
set output [file join $root vivado]
set part xc7z015clg485-2
set jobs $::env(ORB60_LAYER_TIMING_JOBS)
if {[file exists $output]} {error "Refusing to reuse a layer Vivado directory"}
file mkdir $output
set_param general.maxThreads 8
create_project p $output -part $part
set_property target_language Verilog [current_project]
set ip [file join $root ip]
if {![file exists [file join $ip component.xml]]} {error "Missing accepted layer IP"}
set_property ip_repo_paths [list $ip] [current_project]
update_ip_catalog
create_bd_design s
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
source [file join $inputs ps_config.tcl]
set_property -dict [list CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_S_AXI_HP1 {1} \
    CONFIG.PCW_USE_S_AXI_HP2 {1} CONFIG.PCW_USE_S_AXI_HP3 {1}] $ps7
set layer [create_bd_cell -type ip -vlnv xilinx.com:hls:fastv2_layer2_hls:1.0 layer]
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset]
set_property CONFIG.C_EXT_RESET_HIGH {0} $reset
set control [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 control]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $control
make_bd_intf_pins_external [get_bd_intf_pins $ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins $ps7/FIXED_IO]
connect_bd_intf_net [get_bd_intf_pins $ps7/M_AXI_GP0] [get_bd_intf_pins $control/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $control/M00_AXI] [get_bd_intf_pins $layer/s_axi_control]
set converters [list $control]
# Raw read HP0, blur write HP1, resized raw write HP2, point/metadata write HP3.
foreach {bundle hp} {gmem0 0 gmem2 1 gmem3 2 gmem1 3} {
    set ic [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 mem${hp}]
    set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $ic
    connect_bd_intf_net [get_bd_intf_pins $layer/m_axi_$bundle] [get_bd_intf_pins $ic/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins $ic/M00_AXI] [get_bd_intf_pins $ps7/S_AXI_HP${hp}]
    lappend converters $ic
}
set clock [get_bd_pins $ps7/FCLK_CLK0]
set reset_n [get_bd_pins $reset/peripheral_aresetn]
connect_bd_net $clock [get_bd_pins $reset/slowest_sync_clk] [get_bd_pins $layer/ap_clk] [get_bd_pins $ps7/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins $ps7/FCLK_RESET0_N] [get_bd_pins $reset/ext_reset_in]
connect_bd_net $reset_n [get_bd_pins $layer/ap_rst_n]
foreach hp {0 1 2 3} {connect_bd_net $clock [get_bd_pins $ps7/S_AXI_HP${hp}_ACLK]}
foreach ic $converters {
    foreach pin [get_bd_pins -quiet ${ic}/*ACLK] {connect_bd_net $clock $pin}
    foreach pin [get_bd_pins -quiet ${ic}/*ARESETN] {connect_bd_net $reset_n $pin}
}
assign_bd_address -offset 0x43C00000 -range 64K -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs layer/s_axi_control/Reg]
assign_bd_address
validate_bd_design
save_bd_design
set bd [get_files [file join $output p.srcs sources_1 bd s s.bd]]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top s_wrapper [current_fileset]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {error "Layer top synthesis failed"}
open_run synth_1
report_utilization -file [file join $output post_synth_utilization.rpt]
report_timing_summary -file [file join $output post_synth_timing.rpt]
set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
launch_runs impl_1 -to_step route_design -jobs $jobs
wait_on_run impl_1
set run_dir [get_property DIRECTORY [get_runs impl_1]]
if {![file exists [file join $run_dir .route_design.end.rst]] ||
    [file exists [file join $run_dir .route_design.error.rst]] ||
    ![file exists [file join $run_dir s_wrapper_routed.dcp]]} {
    error "Missing completed layer route evidence: [get_property STATUS [get_runs impl_1]]"
}
# Vivado 2024.2 can mark the next enabled step as not launched after -to_step.
# The completed checkpoint is authoritative; close project/run state entirely.
set routed_checkpoint [file join $run_dir s_wrapper_routed.dcp]
close_project
open_checkpoint $routed_checkpoint
source [file join $inputs timing_checks.tcl]
source [file join $inputs route_reports.tcl]
orb60_report_routed $output $part 100 fastv2_layer2_hls 1 "shared-reader 2PPC layer routed top; protocol/descriptor/board acceptance pending"
exit 0
