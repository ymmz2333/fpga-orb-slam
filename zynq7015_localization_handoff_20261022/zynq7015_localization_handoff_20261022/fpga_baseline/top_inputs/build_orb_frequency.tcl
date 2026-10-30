# Timing integration only: accepted layer + exact descriptor, shared PS7 DDR.
set root [file normalize $::env(ORB60_ORB_TIMING_ROOT)]
set inputs [file join $root inputs]
set output [file join $root vivado]
set part xc7z015clg485-2
set jobs $::env(ORB60_ORB_TIMING_JOBS)
set frequency 100
if {[info exists ::env(ORB60_ORB_TIMING_FREQUENCY)]} {set frequency $::env(ORB60_ORB_TIMING_FREQUENCY)}
if {![string is double -strict $frequency] || $frequency<125 || $frequency>200} {error "Unsupported frequency experiment: $frequency"}
if {[file exists $output]} {error "Refusing existing integrated Vivado project"}
file mkdir $output
set_param general.maxThreads 8
create_project p $output -part $part
set_property target_language Verilog [current_project]
foreach name {layer desc} {
    if {![file exists [file join $root ip $name component.xml]]} {error "Missing accepted $name IP"}
}
set_property ip_repo_paths [list [file join $root ip layer] [file join $root ip desc]] [current_project]
update_ip_catalog
create_bd_design s
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
source [file join $inputs ps_config.tcl]
set_property -dict [list CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 100 \
    CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_S_AXI_HP1 {1} \
    CONFIG.PCW_USE_S_AXI_HP2 {1} CONFIG.PCW_USE_S_AXI_HP3 {1}] $ps7
set layer [create_bd_cell -type ip -vlnv xilinx.com:hls:fastv2_layer2_hls:1.0 layer]
set desc [create_bd_cell -type ip -vlnv xilinx.com:hls:fastv2_descriptor_hls:1.0 desc]
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset]
set_property CONFIG.C_EXT_RESET_HIGH {0} $reset
# Mature AMD MMCM IP: PS FCLK remains100 MHz; all PL/HP/GP clocks use clk_out1.
set clockgen [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clockgen]
set_property -dict [list CONFIG.PRIM_IN_FREQ {100.000} CONFIG.PRIM_SOURCE {No_buffer} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $frequency CONFIG.CLKOUT1_DRIVES {BUFG} \
    CONFIG.USE_RESET {true} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.USE_LOCKED {true}] $clockgen
connect_bd_net [get_bd_pins $ps7/FCLK_CLK0] [get_bd_pins $clockgen/clk_in1]
connect_bd_net [get_bd_pins $ps7/FCLK_RESET0_N] [get_bd_pins $clockgen/resetn]
connect_bd_net [get_bd_pins $clockgen/locked] [get_bd_pins $reset/dcm_locked]
set control [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 control]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] $control
make_bd_intf_pins_external [get_bd_intf_pins $ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins $ps7/FIXED_IO]
connect_bd_intf_net [get_bd_intf_pins $ps7/M_AXI_GP0] [get_bd_intf_pins $control/S00_AXI]
set control_slices [list]
set control_slice_mode $::env(ORB60_CONTROL_SLICE_MODE)
foreach {core control_port} [list $layer M00_AXI $desc M01_AXI] {
    if {$control_slice_mode==0} {
        connect_bd_intf_net [get_bd_intf_pins $control/$control_port] [get_bd_intf_pins $core/s_axi_control]
    } else {
        set slice [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 ${core}_control_slice]
        set_property -dict [list CONFIG.PROTOCOL {AXI4LITE} CONFIG.ADDR_WIDTH {32} \
            CONFIG.DATA_WIDTH {32} CONFIG.REG_AW $control_slice_mode CONFIG.REG_W $control_slice_mode \
            CONFIG.REG_B $control_slice_mode CONFIG.REG_AR $control_slice_mode CONFIG.REG_R $control_slice_mode] $slice
        connect_bd_intf_net [get_bd_intf_pins $control/$control_port] [get_bd_intf_pins $slice/S_AXI]
        connect_bd_intf_net [get_bd_intf_pins $slice/M_AXI] [get_bd_intf_pins $core/s_axi_control]
        lappend control_slices $slice
    }
}
set converters [list $control]
# Pair raw accesses HP0, blur accesses HP1, next-image/features HP2,
# points + statistics HP3. Each AMD interconnect arbitrates 2 AXI4 masters
# and supplies the required 64-bit AXI3 PS7 HP protocol conversion.
foreach {layer_bundle desc_bundle hp} {gmem0 gmem0 0 gmem2 gmem1 1 gmem3 gmem3 2 gmem1 gmem2 3} {
    set ic [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 mem${hp}]
    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $ic
    connect_bd_intf_net [get_bd_intf_pins $layer/m_axi_$layer_bundle] [get_bd_intf_pins $ic/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins $desc/m_axi_$desc_bundle] [get_bd_intf_pins $ic/S01_AXI]
    connect_bd_intf_net [get_bd_intf_pins $ic/M00_AXI] [get_bd_intf_pins $ps7/S_AXI_HP${hp}]
    lappend converters $ic
}
set clock [get_bd_pins $clockgen/clk_out1]
set reset_n [get_bd_pins $reset/peripheral_aresetn]
connect_bd_net $clock [get_bd_pins $reset/slowest_sync_clk] [get_bd_pins $ps7/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins $ps7/FCLK_RESET0_N] [get_bd_pins $reset/ext_reset_in]
foreach core [list $layer $desc] {
    connect_bd_net $clock [get_bd_pins $core/ap_clk]
    connect_bd_net $reset_n [get_bd_pins $core/ap_rst_n]
}
foreach hp {0 1 2 3} {connect_bd_net $clock [get_bd_pins $ps7/S_AXI_HP${hp}_ACLK]}
foreach slice $control_slices {
    connect_bd_net $clock [get_bd_pins $slice/aclk]
    connect_bd_net $reset_n [get_bd_pins $slice/aresetn]
}
foreach ic $converters {
    foreach pin [get_bd_pins -quiet ${ic}/*ACLK] {connect_bd_net $clock $pin}
    foreach pin [get_bd_pins -quiet ${ic}/*ARESETN] {connect_bd_net $reset_n $pin}
}
assign_bd_address -offset 0x43C00000 -range 64K -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs layer/s_axi_control/Reg]
assign_bd_address -offset 0x43C10000 -range 64K -target_address_space [get_bd_addr_spaces ps7/Data] [get_bd_addr_segs desc/s_axi_control/Reg]
assign_bd_address
validate_bd_design
save_bd_design
set clock_config [open [file join $output post_clock_config.tsv] w]
foreach property {CONFIG.PRIM_IN_FREQ CONFIG.PRIM_SOURCE CONFIG.CLKOUT1_REQUESTED_OUT_FREQ CONFIG.CLKOUT1_JITTER CONFIG.MMCM_DIVCLK_DIVIDE CONFIG.MMCM_CLKFBOUT_MULT_F CONFIG.MMCM_CLKOUT0_DIVIDE_F} {
    puts $clock_config "$property\t[get_property $property $clockgen]"
}
puts $clock_config "CONTROL_SLICE_MODE\t$control_slice_mode"
close $clock_config
if {[info exists ::env(ORB60_FREQUENCY_VALIDATE_ONLY)] && $::env(ORB60_FREQUENCY_VALIDATE_ONLY)==1} {
    puts "FREQUENCY_BD_VALIDATE_PASS frequency=$frequency register_slice_mode=$control_slice_mode"
    close_project
    exit 0
}
set bd [get_files [file join $output p.srcs sources_1 bd s s.bd]]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top s_wrapper [current_fileset]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {error "Integrated synthesis failed"}
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
    error "Missing completed integrated route: [get_property STATUS [get_runs impl_1]]"
}
set checkpoint [file join $run_dir s_wrapper_routed.dcp]
close_project
open_checkpoint $checkpoint
set expected_period [expr {1000.0/$frequency}]
set clock_proof [open [file join $output post_route_clocks.tsv] w]
set clock_match 0
foreach routed_clock [get_clocks] {
    set routed_period [get_property PERIOD $routed_clock]
    puts $clock_proof "[get_property NAME $routed_clock]\t$routed_period"
    # Vivado writes MMCM clock periods to1ps precision. This compares the clock
    # identity only; every setup/hold path is still tested against its real constraint.
    if {abs($routed_period-$expected_period)<=0.0005} {set clock_match 1}
}
close $clock_proof
if {!$clock_match} {error "No routed clock matches requested $frequency MHz"}
source [file join $inputs timing_checks.tcl]
source [file join $inputs route_reports.tcl]
set ppc 2
if {[info exists ::env(ORB60_ORB_TIMING_PPC)]} {set ppc $::env(ORB60_ORB_TIMING_PPC)}
orb60_report_routed $output $part $frequency fastv2_layer2_hls 1 "${ppc}PPC layer + exact A32 descriptor complete routed top; candidate joint DDR/protocol/PS/board gates pending"
exit 0
