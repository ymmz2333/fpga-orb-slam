# Authored full KV260 top: retained 64-bit ORB HLS + official DPUCZDX8G 4.0.
# No board programming. No black-box DPU, copied routed shell or separate bitstreams.
set root [file normalize $::env(FPGA_PROJECT_ROOT)]
set script_dir [file dirname [file normalize [info script]]]
set job [file normalize $::env(KV260_UNIFIED_JOB)]
set project_dir [file join [file normalize $::env(KV260_VIVADO_SCRATCH)] [file tail $job]]
file mkdir $job
cd $job
set_param general.maxThreads 4
proc wire {src args} {
    set pins [list [get_bd_pins $src]]
    foreach dst $args {lappend pins [get_bd_pins $dst]}
    connect_bd_net {*}$pins
}
proc axi {src dst} {connect_bd_intf_net [get_bd_intf_pins $src] [get_bd_intf_pins $dst]}
proc sc {name ns nm clk reset} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 $name
    set_property -dict [list CONFIG.NUM_SI $ns CONFIG.NUM_MI $nm CONFIG.NUM_CLKS 1] [get_bd_cells $name]
    wire $clk $name/aclk
    wire $reset $name/aresetn
}
if {$::env(KV260_UNIFIED_MODE) eq "build"} {
    set layer [file join $root orb60 build kv260_system hls_layer2_150_20261102]
    set desc [file join $root orb60 build kv260_system hls_descriptor_150_20261102]
    foreach path [list $layer $desc] {
        if {![file exists [file join $path unit_pass.stamp]]} {error "Accepted HLS unit required: $path"}
    }
    set dpu_repo [file join $root orb60 build kv260_system vendor_sources dpu_trd DPUCZDX8G dpu_ip]
    create_project kv260_orb_dpu $project_dir -part xck26-sfvc784-2LV-c
    set_property board_part xilinx.com:kv260_som:part0:1.4 [current_project]
    set_property ip_repo_paths [list $dpu_repo [file join $layer project solution1 impl ip] [file join $desc project solution1 impl ip]] [current_project]
    update_ip_catalog
    create_bd_design system
    create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} [get_bd_cells ps]
    set_property -dict [list CONFIG.PSU__USE__M_AXI_GP0 1 CONFIG.PSU__USE__M_AXI_GP1 0 CONFIG.PSU__USE__M_AXI_GP2 0 \
        CONFIG.PSU__USE__S_AXI_GP0 1 CONFIG.PSU__USE__S_AXI_GP1 0 CONFIG.PSU__USE__S_AXI_GP2 1 \
        CONFIG.PSU__USE__S_AXI_GP3 1 CONFIG.PSU__USE__S_AXI_GP4 1 CONFIG.PSU__USE__S_AXI_GP5 1 \
        CONFIG.PSU__USE__S_AXI_GP6 0 CONFIG.PSU__USE__IRQ0 1 \
        CONFIG.PSU__FPGA_PL0_ENABLE 1 CONFIG.PSU__FPGA_PL1_ENABLE 0 \
        CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ 100] [get_bd_cells ps]
    create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clocks
    set reference_mhz [expr {[get_property CONFIG.FREQ_HZ [get_bd_pins ps/pl_clk0]] / 1000000.0}]
    set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ $reference_mhz CONFIG.NUM_OUT_CLKS 3 CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 150 \
        CONFIG.CLKOUT2_USED true CONFIG.CLKOUT2_REQUESTED_OUT_FREQ 300 CONFIG.CLKOUT3_USED true \
        CONFIG.CLKOUT3_REQUESTED_OUT_FREQ 600 CONFIG.RESET_TYPE ACTIVE_LOW] [get_bd_cells clocks]
    wire ps/pl_clk0 clocks/clk_in1
    wire ps/pl_resetn0 clocks/resetn
    foreach {name clk} {reset_orb clocks/clk_out1 reset_dpu clocks/clk_out2 reset_dsp clocks/clk_out3} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 $name
        wire $clk $name/slowest_sync_clk
        wire ps/pl_resetn0 $name/ext_reset_in
        wire clocks/locked $name/dcm_locked
    }
    create_bd_cell -type ip -vlnv xilinx.com:hls:fastv2_layer2_hls:1.0 layer
    create_bd_cell -type ip -vlnv xilinx.com:hls:fastv2_descriptor_hls:1.0 descriptor
    foreach core {layer descriptor} {
        wire clocks/clk_out1 $core/ap_clk
        wire reset_orb/peripheral_aresetn $core/ap_rst_n
    }
    create_bd_cell -type ip -vlnv xilinx.com:ip:dpuczdx8g:4.0 dpu
    # 56 URAMs => 10 image banks +17 weight banks +1 bias bank (2 URAM/bank).
    # Buffer placement does not change the compiler fingerprint.
    set_property -dict [list CONFIG.VER_DPU_NUM 1 CONFIG.ARCH 4096 CONFIG.ARCH_IMG_BKGRP 2 \
        CONFIG.LOAD_AUGM 1 CONFIG.CONV_RELU_ADDON 3 CONFIG.ALU_PARALLEL_USER 4 CONFIG.ALU_LEAKYRELU 0 \
        CONFIG.CONV_WR_PARALLEL 1 CONFIG.SFM_ENA 0 CONFIG.S_AXI_CLK_INDEPENDENT 1 CONFIG.CLK_GATING_ENA 0 \
        CONFIG.CONV_DSP_CASC_MAX 4 CONFIG.CONV_DSP_ACCU_ENA 1 CONFIG.URAM_N_USER 56 CONFIG.TIMESTAMP_ENA 0 \
        CONFIG.GP_ID_BW 6 CONFIG.HP0_ID_BW 6 CONFIG.HP1_ID_BW 6] [get_bd_cells dpu]
    wire clocks/clk_out1 dpu/s_axi_aclk ps/maxihpm0_fpd_aclk
    wire clocks/clk_out2 dpu/m_axi_dpu_aclk ps/saxihpc0_fpd_aclk ps/saxihp0_fpd_aclk ps/saxihp1_fpd_aclk
    wire clocks/clk_out3 dpu/dpu_2x_clk
    wire reset_orb/peripheral_aresetn dpu/s_axi_aresetn
    wire reset_dpu/peripheral_aresetn dpu/m_axi_dpu_aresetn
    wire reset_dsp/peripheral_aresetn dpu/dpu_2x_resetn
    wire clocks/clk_out1 ps/saxihp2_fpd_aclk ps/saxihp3_fpd_aclk
    # Share the wide AXI -> AXI-Lite conversion before address fanout. All
    # consumers are 32-bit CSR ports; no per-slave full-AXI packet FIFOs needed.
    # Keep PS HPM0 at its board-preset 128 bits (boot/AFI settings unchanged).
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dwidth_converter:2.1 control_width
    set_property -dict [list CONFIG.SI_DATA_WIDTH 128 CONFIG.MI_DATA_WIDTH 32] [get_bd_cells control_width]
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter:2.1 control_protocol
    set_property -dict [list CONFIG.SI_PROTOCOL AXI4 CONFIG.MI_PROTOCOL AXI4LITE CONFIG.DATA_WIDTH 32] [get_bd_cells control_protocol]
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 control
    set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 3] [get_bd_cells control]
    wire clocks/clk_out1 control_width/s_axi_aclk control_protocol/aclk control/ACLK control/S00_ACLK control/M00_ACLK control/M01_ACLK control/M02_ACLK
    wire reset_orb/interconnect_aresetn control_width/s_axi_aresetn control_protocol/aresetn control/ARESETN control/S00_ARESETN control/M00_ARESETN control/M01_ARESETN control/M02_ARESETN
    axi ps/M_AXI_HPM0_FPD control_width/S_AXI
    axi control_width/M_AXI control_protocol/S_AXI
    axi control_protocol/M_AXI control/S00_AXI
    foreach {port target} {M00_AXI layer/s_axi_control M01_AXI descriptor/s_axi_control M02_AXI dpu/S_AXI} {axi control/$port $target}
    # Pair image/descriptor traffic into two independent PS HP ports.
    foreach {name hp sources} {
        orb_mem0 HP2 {layer/m_axi_gmem0 layer/m_axi_gmem2 descriptor/m_axi_gmem0 descriptor/m_axi_gmem1}
        orb_mem1 HP3 {layer/m_axi_gmem1 layer/m_axi_gmem3 descriptor/m_axi_gmem2 descriptor/m_axi_gmem3}
    } {
        sc $name 4 1 clocks/clk_out1 reset_orb/interconnect_aresetn
        set i 0
        foreach source $sources {axi $source [format {%s/S%02d_AXI} $name $i]; incr i}
        axi $name/M00_AXI ps/S_AXI_${hp}_FPD
    }
    # Instruction traffic still requires width conversion. Dedicated data
    # masters and PS HP ports already have matching 128-bit data / 6-bit IDs.
    sc dpu_instr 1 1 clocks/clk_out2 reset_dpu/interconnect_aresetn
    axi dpu/DPU0_M_AXI_INSTR dpu_instr/S00_AXI
    axi dpu_instr/M00_AXI ps/S_AXI_HPC0_FPD
    axi dpu/DPU0_M_AXI_DATA0 ps/S_AXI_HP0_FPD
    axi dpu/DPU0_M_AXI_DATA1 ps/S_AXI_HP1_FPD
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 interrupts
    set_property CONFIG.NUM_PORTS 3 [get_bd_cells interrupts]
    wire dpu/dpu0_interrupt interrupts/In0
    wire layer/interrupt interrupts/In1
    wire descriptor/interrupt interrupts/In2
    wire interrupts/dout ps/pl_ps_irq0
    assign_bd_address -offset 0xA0000000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs layer/s_axi_control/Reg]
    assign_bd_address -offset 0xA0010000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs descriptor/s_axi_control/Reg]
    set dpu_seg [get_bd_addr_segs dpu/S_AXI/*]
    if {[llength $dpu_seg] != 1} {error "Expected one DPU register segment: $dpu_seg"}
    # Official DPU IP requires a 16 MiB aperture (not the 64 KiB HLS aperture).
    assign_bd_address -offset 0xA1000000 -range 16M -target_address_space [get_bd_addr_spaces ps/Data] $dpu_seg
    assign_bd_address
    validate_bd_design
    save_bd_design
    write_bd_tcl -force [file join $job system_generated.tcl]
    set f [open [file join $job address_map.tsv] w]
    foreach seg [get_bd_addr_segs -hierarchical] {
        if {[get_property -quiet OFFSET $seg] ne ""} {puts $f "$seg\t[get_property OFFSET $seg]\t[get_property RANGE $seg]"}
    }
    close $f
    set f [open [file join $job dpu_properties.tsv] w]
    foreach prop [lsort [list_property [get_bd_cells dpu]]] {if {[string match CONFIG.* $prop]} {puts $f "$prop\t[get_property $prop [get_bd_cells dpu]]"}}
    close $f
    set bd [get_files system.bd]
    set_property synth_checkpoint_mode None $bd
    generate_target all $bd
    set generated_arch [file join $project_dir kv260_orb_dpu.gen sources_1 bd system ip system_dpu_0 arch.json]
    if {![file exists $generated_arch]} {error "DPU-generated architecture missing"}
    file copy -force $generated_arch [file join $job dpu_arch.json]
    set wrapper [make_wrapper -files $bd -top]
    add_files -norecurse $wrapper
    set_property top system_wrapper [current_fileset]
    update_compile_order -fileset sources_1
    set f [open [file join $job project_path.txt] w];puts $f [get_property DIRECTORY [current_project]]/kv260_orb_dpu.xpr;close $f
    launch_runs synth_1 -jobs 4
    wait_on_run synth_1
    if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Unified synthesis failed: [get_property STATUS [get_runs synth_1]]"}
    open_run synth_1
    report_utilization -file [file join $job synthesized_utilization.rpt]
    report_utilization -hierarchical -file [file join $job synthesized_hierarchy.rpt]
    write_checkpoint -force [file join $job synthesized.dcp]
    close_design
    set_property strategy Performance_Explore [get_runs impl_1]
    # Measured baseline failed with congestion level 6 and >92k unrouted nets.
    # Spread placement before route; retain all setup/hold and CDC constraints.
    set_property strategy Congestion_SpreadLogic_high [get_runs impl_1]
    launch_runs impl_1 -to_step route_design -jobs 4
    wait_on_run impl_1
    if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Unified implementation failed: [get_property STATUS [get_runs impl_1]]"}
    open_run impl_1
} else {
    open_project [file join $project_dir kv260_orb_dpu.xpr]
    open_run impl_1
}
write_checkpoint -force [file join $job routed.dcp]
report_utilization -file [file join $job utilization.rpt]
report_utilization -hierarchical -file [file join $job utilization_hierarchical.rpt]
report_design_analysis -congestion -file [file join $job congestion.rpt]
report_route_status -file [file join $job route_status.rpt]
report_drc -file [file join $job drc.rpt]
report_methodology -file [file join $job methodology.rpt]
report_timing_summary -check_timing_verbose -report_unconstrained -file [file join $job timing_summary.rpt]
report_timing -delay_type max -max_paths 30 -nworst 2 -file [file join $job setup_paths.rpt]
report_timing -delay_type min -max_paths 20 -nworst 2 -file [file join $job hold_paths.rpt]
report_clock_interaction -file [file join $job clock_interaction.rpt]
report_cdc -details -file [file join $job cdc.rpt]
check_timing -verbose -file [file join $job check_timing.rpt]
write_hw_platform -fixed -force -file [file join $job kv260_orb_dpu.xsa]
puts "KV260_UNIFIED_ROUTED_REPORTS_COMPLETE $job"
exit
