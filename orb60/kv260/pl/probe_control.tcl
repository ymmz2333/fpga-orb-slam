set root [file normalize $::env(FPGA_PROJECT_ROOT)]
set out [file normalize $::env(KV260_CONTROL_PROBE)]
file mkdir $out
create_project -in_memory -part xck26-sfvc784-2LV-c
create_bd_design control_probe
foreach {name vlnv} {
    width xilinx.com:ip:axi_dwidth_converter:2.1
    protocol xilinx.com:ip:axi_protocol_converter:2.1
    fanout xilinx.com:ip:axi_interconnect:2.1
} {
    create_bd_cell -type ip -vlnv $vlnv $name
    set f [open [file join $out ${name}_properties.tsv] w]
    foreach prop [lsort [list_property [get_bd_cells $name]]] {
        if {[string match CONFIG.* $prop]} {puts $f "$prop\t[get_property $prop [get_bd_cells $name]]"}
    }
    close $f
}
set_property -dict [list CONFIG.SI_DATA_WIDTH 128 CONFIG.MI_DATA_WIDTH 32] [get_bd_cells width]
set_property -dict [list CONFIG.SI_PROTOCOL AXI4 CONFIG.MI_PROTOCOL AXI4LITE CONFIG.DATA_WIDTH 32] [get_bd_cells protocol]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 3] [get_bd_cells fanout]
connect_bd_intf_net [get_bd_intf_pins width/M_AXI] [get_bd_intf_pins protocol/S_AXI]
connect_bd_intf_net [get_bd_intf_pins protocol/M_AXI] [get_bd_intf_pins fanout/S00_AXI]
write_bd_tcl -force [file join $out control_generated.tcl]
puts "CONTROL_WIDTH_PROTOCOL_CONFIGURATION_PASS_NOT_SYSTEM_VALIDATION"
exit
