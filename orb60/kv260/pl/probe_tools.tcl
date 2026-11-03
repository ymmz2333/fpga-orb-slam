set root [file normalize [file join [file dirname [info script]] ../../..]]
set out [file join $root orb60 build kv260_system tool_inventory.txt]
file mkdir [file dirname $out]
set f [open $out w]
puts $f "VIVADO [version -short]"
puts $f "PARTS [get_parts -quiet xck26*]"
puts $f "BOARDS [get_board_parts -quiet *kv260*]"
create_project -in_memory -part xck26-sfvc784-2LV-c
foreach pattern {*zynq_ultra_ps_e* *smartconnect* *axi_register_slice* *DPU* *dpu*} {
    puts $f "IP $pattern [get_ipdefs -quiet $pattern]"
}
close $f
puts "KV260_TOOL_INVENTORY $out"
exit
