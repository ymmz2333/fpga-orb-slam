# Authored complete K26 DPU + point-project platform. No board programming.
# AMD IP: ZynqMP, DPUCZDX8G, AXI conversion, clocks and resets.
set root [file normalize $::env(FPGA_PROJECT_ROOT)]
set job [file normalize $::env(KV260_DPU_ONLY_JOB)]
set project_dir [file join [file normalize $::env(FPGA_VIVADO_BUILD_ROOT)] [file tail $job]]
set mode $::env(KV260_DPU_ONLY_MODE)
set mhz $::env(KV260_DPU_MHZ)
set_param general.maxThreads 4
file mkdir $job
cd $job
proc wire {src args} {
    set pins [list [get_bd_pins $src]]
    foreach dst $args {lappend pins [get_bd_pins $dst]}
    connect_bd_net {*}$pins
}
proc axi {src dst} {connect_bd_intf_net [get_bd_intf_pins $src] [get_bd_intf_pins $dst]}
if {$mode eq "build"} {
    set repo [file join $root orb60 build kv260_system vendor_sources dpu_trd DPUCZDX8G dpu_ip]
    if {![file exists [file join $repo DPUCZDX8G_v4_0_0 component.xml]]} {error "Verified official DPU IP is required"}
    create_project kv260_dpu_points $project_dir -part xck26-sfvc784-2LV-c
    set_property board_part xilinx.com:kv260_som:part0:1.4 [current_project]
    set point_hls [file normalize $::env(POINT_HLS_JOB)]
    set_property ip_repo_paths [list $repo [file join $point_hls project solution1 impl ip]] [current_project]
    update_ip_catalog
    create_bd_design system
    create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} [get_bd_cells ps]
    # HPM0 controls the DPU; HPC0 carries instructions; HP0/HP1 carry data.
    # HP2 carries the point-project kernel; HP3 remains disabled.
    set_property -dict [list CONFIG.PSU__USE__M_AXI_GP0 1 CONFIG.PSU__USE__M_AXI_GP1 0 CONFIG.PSU__USE__M_AXI_GP2 0 \
        CONFIG.PSU__USE__S_AXI_GP0 1 CONFIG.PSU__USE__S_AXI_GP1 0 CONFIG.PSU__USE__S_AXI_GP2 1 \
        CONFIG.PSU__USE__S_AXI_GP3 1 CONFIG.PSU__USE__S_AXI_GP4 1 CONFIG.PSU__USE__S_AXI_GP5 0 \
        CONFIG.PSU__USE__S_AXI_GP6 0 CONFIG.PSU__USE__IRQ0 1 \
        CONFIG.PSU__FPGA_PL0_ENABLE 1 CONFIG.PSU__FPGA_PL1_ENABLE 0 \
        CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ 100] [get_bd_cells ps]
    create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clocks
    set ref_mhz [expr {[get_property CONFIG.FREQ_HZ [get_bd_pins ps/pl_clk0]] / 1000000.0}]
    set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ $ref_mhz CONFIG.NUM_OUT_CLKS 3 \
        CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 150 CONFIG.CLKOUT2_USED true CONFIG.CLKOUT2_REQUESTED_OUT_FREQ $mhz \
        CONFIG.CLKOUT3_USED true CONFIG.CLKOUT3_REQUESTED_OUT_FREQ [expr {2*$mhz}] CONFIG.RESET_TYPE ACTIVE_LOW] [get_bd_cells clocks]
    wire ps/pl_clk0 clocks/clk_in1
    wire ps/pl_resetn0 clocks/resetn
    foreach {name clk} {reset_control clocks/clk_out1 reset_dpu clocks/clk_out2 reset_dsp clocks/clk_out3} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 $name
        wire $clk $name/slowest_sync_clk
        wire ps/pl_resetn0 $name/ext_reset_in
        wire clocks/locked $name/dcm_locked
    }
    create_bd_cell -type ip -vlnv xilinx.com:ip:dpuczdx8g:4.0 dpu
    # Keep the existing MiDaS compiled model's ISA1 B4096 fingerprint.
    set_property -dict [list CONFIG.VER_DPU_NUM 1 CONFIG.ARCH 4096 CONFIG.ARCH_IMG_BKGRP 2 \
        CONFIG.LOAD_AUGM 1 CONFIG.CONV_RELU_ADDON 3 CONFIG.ALU_PARALLEL_USER 4 CONFIG.ALU_LEAKYRELU 0 \
        CONFIG.CONV_WR_PARALLEL 1 CONFIG.SFM_ENA 0 CONFIG.S_AXI_CLK_INDEPENDENT 1 CONFIG.CLK_GATING_ENA 0 \
        CONFIG.CONV_DSP_CASC_MAX 4 CONFIG.CONV_DSP_ACCU_ENA 1 CONFIG.URAM_N_USER 56 CONFIG.TIMESTAMP_ENA 0 \
        CONFIG.GP_ID_BW 2 CONFIG.HP0_ID_BW 6 CONFIG.HP1_ID_BW 6] [get_bd_cells dpu]
    wire clocks/clk_out1 dpu/s_axi_aclk ps/maxihpm0_fpd_aclk
    wire clocks/clk_out2 dpu/m_axi_dpu_aclk ps/saxihpc0_fpd_aclk ps/saxihp0_fpd_aclk ps/saxihp1_fpd_aclk
    wire clocks/clk_out3 dpu/dpu_2x_clk
    wire reset_control/peripheral_aresetn dpu/s_axi_aresetn
    wire reset_dpu/peripheral_aresetn dpu/m_axi_dpu_aresetn
    wire reset_dsp/peripheral_aresetn dpu/dpu_2x_resetn
    # The K26 DPU control slave is full AXI4 (not AXI4-Lite). Let the AMD
    # interconnect propagate USER/ID metadata and adapt 128-bit HPM to 32 bits.
    create_bd_cell -type ip -vlnv xilinx.com:hls:point_project_hls:1.0 point_project
    wire clocks/clk_out1 point_project/ap_clk ps/saxihp2_fpd_aclk
    wire reset_control/peripheral_aresetn point_project/ap_rst_n
    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 control
    set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 2 CONFIG.NUM_CLKS 1] [get_bd_cells control]
    wire clocks/clk_out1 control/aclk
    wire reset_control/interconnect_aresetn control/aresetn
    axi ps/M_AXI_HPM0_FPD control/S00_AXI
    axi control/M00_AXI dpu/S_AXI
    axi control/M01_AXI point_project/s_axi_control
    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 point_mem
    set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells point_mem]
    wire clocks/clk_out1 point_mem/aclk
    wire reset_control/interconnect_aresetn point_mem/aresetn
    axi point_project/m_axi_input_mem point_mem/S00_AXI
    axi point_project/m_axi_output_mem point_mem/S01_AXI
    axi point_mem/M00_AXI ps/S_AXI_HP2_FPD
    create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 dpu_instr
    set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 1] [get_bd_cells dpu_instr]
    wire clocks/clk_out2 dpu_instr/aclk
    wire reset_dpu/interconnect_aresetn dpu_instr/aresetn
    axi dpu/DPU0_M_AXI_INSTR dpu_instr/S00_AXI
    axi dpu_instr/M00_AXI ps/S_AXI_HPC0_FPD
    axi dpu/DPU0_M_AXI_DATA0 ps/S_AXI_HP0_FPD
    axi dpu/DPU0_M_AXI_DATA1 ps/S_AXI_HP1_FPD
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 irq_zero
    set_property -dict [list CONFIG.CONST_WIDTH 6 CONFIG.CONST_VAL 0] [get_bd_cells irq_zero]
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 interrupts
    set_property -dict [list CONFIG.NUM_PORTS 3 CONFIG.IN1_WIDTH 1 CONFIG.IN2_WIDTH 6] [get_bd_cells interrupts]
    wire dpu/dpu0_interrupt interrupts/In0
    wire point_project/interrupt interrupts/In1
    wire irq_zero/dout interrupts/In2
    wire interrupts/dout ps/pl_ps_irq0
    set seg [get_bd_addr_segs dpu/S_AXI/*]
    if {[llength $seg] != 1} {error "Expected exactly one DPU control segment"}
    assign_bd_address -offset 0xA1000000 -range 16M -target_address_space [get_bd_addr_spaces ps/Data] $seg
    assign_bd_address -offset 0xA2000000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] [get_bd_addr_segs point_project/s_axi_control/Reg]
    assign_bd_address
    validate_bd_design
    save_bd_design
    write_bd_tcl -force [file join $job system_generated.tcl]
    set f [open [file join $job bd_inventory.tsv] w]
    foreach cell [get_bd_cells -hierarchical] {puts $f "$cell\t[get_property VLNV $cell]"}
    close $f
    set f [open [file join $job address_map.tsv] w]
    foreach seg [get_bd_addr_segs -hierarchical] {
        if {[get_property -quiet OFFSET $seg] ne ""} {puts $f "$seg\t[get_property OFFSET $seg]\t[get_property RANGE $seg]"}
    }
    close $f
    set f [open [file join $job dpu_properties.tsv] w]
    foreach prop [lsort [list_property [get_bd_cells dpu]]] {
        if {[string match CONFIG.* $prop]} {puts $f "$prop\t[get_property $prop [get_bd_cells dpu]]"}
    }
    close $f
    set bd [get_files system.bd]
    set_property synth_checkpoint_mode None $bd
    generate_target all $bd
    set arch [file join $project_dir kv260_dpu_points.gen sources_1 bd system ip system_dpu_0 arch.json]
    if {![file exists $arch]} {error "Official generated DPU architecture is missing"}
    file copy -force $arch [file join $job dpu_arch.json]
    add_files -norecurse [make_wrapper -files $bd -top]
    set_property top system_wrapper [current_fileset]
    update_compile_order -fileset sources_1
    set f [open [file join $job project_path.txt] w]; puts $f [file join $project_dir kv260_dpu_points.xpr]; close $f
    launch_runs synth_1 -jobs 4
    wait_on_run synth_1
    if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "DPU-only synthesis failed: [get_property STATUS [get_runs synth_1]]"}
    open_run synth_1
    report_utilization -file [file join $job synthesized_utilization.rpt]
    report_utilization -hierarchical -file [file join $job synthesized_hierarchy.rpt]
    write_checkpoint -force [file join $job synthesized.dcp]
    close_design
    set_property strategy Performance_Explore [get_runs impl_1]
    launch_runs impl_1 -to_step route_design -jobs 4
    wait_on_run impl_1
    if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "DPU-only route failed: [get_property STATUS [get_runs impl_1]]"}
    open_run impl_1
} else {
    open_project [file join $project_dir kv260_dpu_points.xpr]
    open_run impl_1
}
source [file join [file dirname [file normalize [info script]]] report_system.tcl]
