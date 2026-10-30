# Vivado 2024.2: R11 three-core baseline or bounded timing candidate.
# No hardware programming. A timing experiment is not a functional release.

set next_root [file normalize [file join [file dirname [info script]] ..]]
if {![info exists ::env(NEXT_BOARD_ROOT)]} { error "Use next/scripts/build_board.ps1" }
set board_root [file normalize $::env(NEXT_BOARD_ROOT)]
set build_dir [file join $board_root vivado]
set ps_config [file join $board_root inputs ps_config.tcl]
set ip_root [file join $board_root projects]
set build_jobs 8
if {[info exists ::env(NEXT_BOARD_JOBS)] &&
    [string is integer -strict $::env(NEXT_BOARD_JOBS)]} {
    set build_jobs $::env(NEXT_BOARD_JOBS)
}
set project_name next_fpga
set design_name next_system
if {[info exists ::env(NEXT_BOARD_SHORT_NAMES)] && $::env(NEXT_BOARD_SHORT_NAMES) eq "1"} {
    set project_name p
    set design_name s
}
set part_name xc7z015clg485-2
set_param general.maxThreads 8

if {[file exists $build_dir]} {
    error "Refusing to reuse an existing next Vivado output directory"
}
file mkdir $build_dir
create_project $project_name $build_dir -part $part_name -force
set_property target_language Verilog [current_project]

set resize_ip [file join $ip_root resize solution1 impl ip]
set front_ip [file join $ip_root front solution1 impl ip]
set gaussian_ip [file join $ip_root gaussian solution1 impl ip]
foreach ip_dir [list $resize_ip $front_ip $gaussian_ip] {
    if {![file exists [file join $ip_dir component.xml]]} {
        error "Missing packaged fastv2 HLS IP at $ip_dir"
    }
}
set_property ip_repo_paths [list $resize_ip $front_ip $gaussian_ip] [current_project]
update_ip_catalog

create_bd_design $design_name
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
source $ps_config
set fabric_frequency 100
if {[info exists ::env(NEXT_BOARD_FREQUENCY_MHZ)]} {set fabric_frequency $::env(NEXT_BOARD_FREQUENCY_MHZ)}
set_property -dict [list \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $fabric_frequency \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP1 {1} \
    CONFIG.PCW_USE_S_AXI_HP2 {1} \
    CONFIG.PCW_USE_S_AXI_HP3 {1}] $ps7

set resize [create_bd_cell -type ip \
    -vlnv xilinx.com:hls:fastv2_resize_hls:1.0 fastv2_resize]
set front_top fastv2_front_hls
if {[info exists ::env(NEXT_BOARD_FRONT_TOP)]} {set front_top $::env(NEXT_BOARD_FRONT_TOP)}
if {$front_top ni {fastv2_front_hls fastv2_front64_hls fastv2_front2_hls}} {error "Invalid front top"}
set front [create_bd_cell -type ip \
    -vlnv xilinx.com:hls:${front_top}:1.0 fastv2_front]
set gaussian [create_bd_cell -type ip \
    -vlnv xilinx.com:hls:fastv2_gaussian_hls:1.0 fastv2_gaussian]
set control_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 control_ic]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {3}] $control_ic

set resize_read_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 resize_read_ic]
set resize_write_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 resize_write_ic]
set front_read_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 front_read_ic]
set front_write_ic [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:axi_interconnect:2.1 front_write_ic]
foreach cell [list $resize_read_ic $resize_write_ic $front_read_ic $front_write_ic] {
    set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $cell
}
# FAST and Gaussian share HP2 read / HP3 write, preserving resize HP0/HP1.
set_property CONFIG.NUM_SI {2} $front_read_ic
set_property CONFIG.NUM_SI {2} $front_write_ic
set reset [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset]
set_property -dict [list CONFIG.C_EXT_RESET_HIGH {0}] $reset

make_bd_intf_pins_external [get_bd_intf_pins $ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins $ps7/FIXED_IO]
connect_bd_intf_net [get_bd_intf_pins $ps7/M_AXI_GP0] \
    [get_bd_intf_pins $control_ic/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $control_ic/M00_AXI] \
    [get_bd_intf_pins $resize/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins $control_ic/M01_AXI] \
    [get_bd_intf_pins $front/s_axi_control]

connect_bd_intf_net [get_bd_intf_pins $control_ic/M02_AXI] \
    [get_bd_intf_pins $gaussian/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins $gaussian/m_axi_gmem0] \
    [get_bd_intf_pins $front_read_ic/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins $gaussian/m_axi_gmem1] \
    [get_bd_intf_pins $front_write_ic/S01_AXI]

set hp_connections [list \
    [list $resize m_axi_gmem0 $resize_read_ic 0] \
    [list $resize m_axi_gmem1 $resize_write_ic 1] \
    [list $front m_axi_gmem0 $front_read_ic 2] \
    [list $front m_axi_gmem1 $front_write_ic 3]]
foreach connection $hp_connections {
    lassign $connection accelerator interface interconnect hp_index
    connect_bd_intf_net [get_bd_intf_pins $accelerator/$interface] \
        [get_bd_intf_pins $interconnect/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins $interconnect/M00_AXI] \
        [get_bd_intf_pins $ps7/S_AXI_HP${hp_index}]
}

set fabric_clock [get_bd_pins $ps7/FCLK_CLK0]
set fabric_reset_n [get_bd_pins $reset/peripheral_aresetn]
connect_bd_net $fabric_clock [get_bd_pins $reset/slowest_sync_clk]
connect_bd_net [get_bd_pins $ps7/FCLK_RESET0_N] [get_bd_pins $reset/ext_reset_in]
connect_bd_net $fabric_clock [get_bd_pins $ps7/M_AXI_GP0_ACLK]
foreach index {0 1 2 3} {
    connect_bd_net $fabric_clock [get_bd_pins $ps7/S_AXI_HP${index}_ACLK]
}
connect_bd_net $fabric_clock [get_bd_pins $resize/ap_clk] [get_bd_pins $front/ap_clk] [get_bd_pins $gaussian/ap_clk]
connect_bd_net $fabric_reset_n [get_bd_pins $resize/ap_rst_n] [get_bd_pins $front/ap_rst_n] [get_bd_pins $gaussian/ap_rst_n]

# @brief Connect all clock and reset pins of one AXI Interconnect.
# @param cell Block-design AXI Interconnect cell object.
proc connect_interconnect_domain {cell} {
    foreach pin [get_bd_pins -quiet ${cell}/*ACLK] {
        connect_bd_net [get_bd_pins ps7/FCLK_CLK0] $pin
    }
    foreach pin [get_bd_pins -quiet ${cell}/*ARESETN] {
        connect_bd_net [get_bd_pins reset/peripheral_aresetn] $pin
    }
}
foreach cell [list $control_ic $resize_read_ic $resize_write_ic \
                   $front_read_ic $front_write_ic] {
    connect_interconnect_domain $cell
}

# Explicitly fixed MMIO bases, also checked against PS header during preflight.
foreach {name offset} {front 0x43C00000 resize 0x43C10000 gaussian 0x43C20000} {
    assign_bd_address -offset $offset -range 64K \
        -target_address_space [get_bd_addr_spaces ps7/Data] \
        [get_bd_addr_segs fastv2_${name}/s_axi_control/Reg]
}
assign_bd_address
validate_bd_design
save_bd_design
set bd_file [get_files [file join $build_dir $project_name.srcs \
    sources_1 bd $design_name ${design_name}.bd]]
generate_target all $bd_file
add_files -norecurse [make_wrapper -files $bd_file -top]
set_property top ${design_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

if {[info exists ::env(NEXT_BOARD_SETUP_ONLY)] &&
    $::env(NEXT_BOARD_SETUP_ONLY) eq "1"} {
    set stamp [open [file join $build_dir .vivado_setup_success] w]
    puts $stamp "NEXT_BOARD_VIVADO_SETUP_SUCCESS"
    close $stamp
    puts "NEXT_BOARD_VIVADO_SETUP_PASS"
    exit 0
}

launch_runs synth_1 -jobs $build_jobs
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "next Vivado synthesis did not complete successfully"
}
open_run synth_1
report_utilization -file [file join $build_dir post_synth_utilization.rpt]
report_timing_summary -file [file join $build_dir post_synth_timing.rpt]

set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
set timing_only 0
if {[info exists ::env(NEXT_BOARD_TIMING_ONLY)]} {set timing_only $::env(NEXT_BOARD_TIMING_ONLY)}
set final_step write_bitstream
if {$timing_only} {set final_step route_design}
launch_runs impl_1 -to_step $final_step -jobs $build_jobs
wait_on_run impl_1
set implementation_status [get_property STATUS [get_runs impl_1]]
if {$timing_only} {
    # STATUS describes the next enabled step in 2024.2 when -to_step stops
    # before post-route phys_opt. Require this unique run's completion marker,
    # absence of its error marker and the actual routed checkpoint; the shared
    # post-check additionally requires every routable net to be fully routed.
    set run_dir [get_property DIRECTORY [get_runs impl_1]]
    if {![file exists [file join $run_dir .route_design.end.rst]] ||
        [file exists [file join $run_dir .route_design.error.rst]] ||
        ![file exists [file join $run_dir ${design_name}_wrapper_routed.dcp]]} {
        error "Missing completed route_design evidence: $implementation_status"
    }
} elseif {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "next Vivado implementation did not complete $final_step: $implementation_status"
}
if {$timing_only} {
    set routed_checkpoint [file join $run_dir ${design_name}_wrapper_routed.dcp]
    close_project
    open_checkpoint $routed_checkpoint
} else {
    open_run impl_1
}
if {$timing_only} {phys_opt_design -directive Explore}
source [file join [file dirname [info script]] timing_checks.tcl]
source [file join [file dirname [info script]] route_reports.tcl]
orb60_report_routed $build_dir $part_name $fabric_frequency $front_top $timing_only
