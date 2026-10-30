"""Create the authored bounded frequency flow from the strict retained flow.

The changes are explicit string assertions; original release scripts stay intact.
This generator never reads or edits generated HLS/Vivado RTL.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def replace(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new)

tcl=(ROOT/'vivado/build_orb_system.tcl').read_text(encoding='utf-8-sig')
tcl=replace(tcl,'if {$frequency ni {100 125}} {error "Unsupported bounded timing frequency: $frequency"}',
    'if {![string is double -strict $frequency] || $frequency<125 || $frequency>200} {error "Unsupported frequency experiment: $frequency"}')
tcl=replace(tcl,'CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $frequency','CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 100')
tcl=replace(tcl,'set_property CONFIG.C_EXT_RESET_HIGH {0} $reset',
'''set_property CONFIG.C_EXT_RESET_HIGH {0} $reset
# Mature AMD MMCM IP: PS FCLK remains100 MHz; all PL/HP/GP clocks use clk_out1.
set clockgen [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clockgen]
set_property -dict [list CONFIG.PRIM_IN_FREQ {100.000} CONFIG.PRIM_SOURCE {No_buffer} \\
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $frequency CONFIG.CLKOUT1_DRIVES {BUFG} \\
    CONFIG.USE_RESET {true} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.USE_LOCKED {true}] $clockgen
connect_bd_net [get_bd_pins $ps7/FCLK_CLK0] [get_bd_pins $clockgen/clk_in1]
connect_bd_net [get_bd_pins $ps7/FCLK_RESET0_N] [get_bd_pins $clockgen/resetn]
connect_bd_net [get_bd_pins $clockgen/locked] [get_bd_pins $reset/dcm_locked]''')
tcl=replace(tcl,'''connect_bd_intf_net [get_bd_intf_pins $control/M00_AXI] [get_bd_intf_pins $layer/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins $control/M01_AXI] [get_bd_intf_pins $desc/s_axi_control]''',
'''set control_slices [list]
set control_slice_mode $::env(ORB60_CONTROL_SLICE_MODE)
foreach {core control_port} [list $layer M00_AXI $desc M01_AXI] {
    if {$control_slice_mode==0} {
        connect_bd_intf_net [get_bd_intf_pins $control/$control_port] [get_bd_intf_pins $core/s_axi_control]
    } else {
        set slice [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 ${core}_control_slice]
        set_property -dict [list CONFIG.PROTOCOL {AXI4LITE} CONFIG.ADDR_WIDTH {32} \\
            CONFIG.DATA_WIDTH {32} CONFIG.REG_AW $control_slice_mode CONFIG.REG_W $control_slice_mode \\
            CONFIG.REG_B $control_slice_mode CONFIG.REG_AR $control_slice_mode CONFIG.REG_R $control_slice_mode] $slice
        connect_bd_intf_net [get_bd_intf_pins $control/$control_port] [get_bd_intf_pins $slice/S_AXI]
        connect_bd_intf_net [get_bd_intf_pins $slice/M_AXI] [get_bd_intf_pins $core/s_axi_control]
        lappend control_slices $slice
    }
}''')
tcl=replace(tcl,'set clock [get_bd_pins $ps7/FCLK_CLK0]', 'set clock [get_bd_pins $clockgen/clk_out1]')
tcl=replace(tcl,'foreach ic $converters {','''foreach slice $control_slices {
    connect_bd_net $clock [get_bd_pins $slice/aclk]
    connect_bd_net $reset_n [get_bd_pins $slice/aresetn]
}
foreach ic $converters {''')
tcl=replace(tcl,'save_bd_design\nset bd', '''save_bd_design
set clock_config [open [file join $output post_clock_config.tsv] w]
foreach property {CONFIG.PRIM_IN_FREQ CONFIG.PRIM_SOURCE CONFIG.CLKOUT1_REQUESTED_OUT_FREQ CONFIG.CLKOUT1_JITTER CONFIG.MMCM_DIVCLK_DIVIDE CONFIG.MMCM_CLKFBOUT_MULT_F CONFIG.MMCM_CLKOUT0_DIVIDE_F} {
    puts $clock_config "$property\\t[get_property $property $clockgen]"
}
puts $clock_config "CONTROL_SLICE_MODE\\t$control_slice_mode"
close $clock_config
if {[info exists ::env(ORB60_FREQUENCY_VALIDATE_ONLY)] && $::env(ORB60_FREQUENCY_VALIDATE_ONLY)==1} {
    puts "FREQUENCY_BD_VALIDATE_PASS frequency=$frequency register_slice_mode=$control_slice_mode"
    close_project
    exit 0
}
set bd''')
tcl=replace(tcl,'if {abs($routed_period-$expected_period)<0.000001}',
'''# Vivado writes MMCM clock periods to1ps precision. This compares the clock
    # identity only; every setup/hold path is still tested against its real constraint.
    if {abs($routed_period-$expected_period)<=0.0005}''')
(ROOT/'vivado/build_orb_frequency.tcl').write_text(tcl,encoding='utf-8')

ps=(ROOT/'scripts/orb_timing.ps1').read_text(encoding='utf-8-sig')
ps=replace(ps,'[ValidateSet(100,125)][int]$FrequencyMHz=100',
    "[ValidateRange(125,200)][double]$FrequencyMHz=150,[ValidateSet('none','light','full')][string]$ControlSlices='light'")
ps=ps.replace('build_orb_system.tcl','build_orb_frequency.tcl')
ps=replace(ps,"$env:ORB60_ORB_TIMING_FREQUENCY=$FrequencyMHz",'''$env:ORB60_ORB_TIMING_FREQUENCY=$FrequencyMHz.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
$env:ORB60_CONTROL_SLICE_MODE=@{none=0;light=7;full=1}[$ControlSlices]''')
ps=replace(ps,"$orbState['FrameJob']=$FrameJob;", "$orbState['ClockSource']='AMD Clocking Wizard MMCM from100MHz PS FCLK';$orbState['ControlSlices']=$ControlSlices;\n$orbState['FrameJob']=$FrameJob;")
ps=replace(ps,'$orbFramePerformance.frequency_mhz -ne $FrequencyMHz',
    "[int]$orbFramePerformance.clock_period_ps -ne [int][Math]::Round(1000000.0/$FrequencyMHz)")
(ROOT/'scripts/orb_frequency_timing.ps1').write_text(ps,encoding='utf-8')
print('AUTHORED_FREQUENCY_FLOW_CREATED')
