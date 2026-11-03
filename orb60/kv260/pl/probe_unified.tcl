# Read-only compatibility/configuration probe for the official DPU IP on K26.
set root [file normalize [file join [file dirname [info script]] ../../..]]
set out [file join $root orb60 build kv260_system unified_probe_20261102]
file mkdir $out
cd $out
create_project probe [file join $out project] -part xck26-sfvc784-2LV-c -force
set_property board_part xilinx.com:kv260_som:part0:1.4 [current_project]
set_property ip_repo_paths [list [file join $root orb60 build kv260_system vendor_sources dpu_trd DPUCZDX8G dpu_ip]] [current_project]
update_ip_catalog
create_bd_design probe
create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} [get_bd_cells ps]
create_bd_cell -type ip -vlnv xilinx.com:ip:dpuczdx8g:4.0 dpu
set_property -dict [list CONFIG.VER_DPU_NUM 1 CONFIG.ARCH 4096 CONFIG.ARCH_IMG_BKGRP 2 CONFIG.LOAD_AUGM 1 CONFIG.CONV_RELU_ADDON 3 CONFIG.ALU_PARALLEL_USER 4 CONFIG.ALU_LEAKYRELU 0 CONFIG.CONV_WR_PARALLEL 1 CONFIG.SFM_ENA 0 CONFIG.S_AXI_CLK_INDEPENDENT 1 CONFIG.CLK_GATING_ENA 0 CONFIG.CONV_DSP_CASC_MAX 4 CONFIG.CONV_DSP_ACCU_ENA 1 CONFIG.URAM_N_USER 23 CONFIG.TIMESTAMP_ENA 0] [get_bd_cells dpu]
set f [open [file join $out properties.txt] w]
puts $f "Vivado [version -short]"
puts $f "DPU [get_ipdefs -quiet *dpuczdx8g*]"
foreach cell {ps dpu} {
    puts $f "CELL $cell"
    foreach prop [lsort [list_property [get_bd_cells $cell]]] {
        if {[string match CONFIG.* $prop]} {puts $f "$prop [get_property $prop [get_bd_cells $cell]]"}
    }
    puts $f "INTERFACES [get_bd_intf_pins $cell/*]"
    puts $f "PINS [get_bd_pins $cell/*]"
}
close $f
save_bd_design
puts "UNIFIED_PROBE_DONE $out"
exit
