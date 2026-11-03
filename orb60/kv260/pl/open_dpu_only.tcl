# Open the exact final checkpoint, including retained post-route refinement.
if {[llength $argv] != 1} {error "Usage: vivado -mode gui -source open_dpu_only.tcl -tclargs <job>"}
set job [file normalize [lindex $argv 0]]
if {![file exists [file join $job static_pass.stamp]]} {error "No passing full-top static evidence in $job"}
open_checkpoint [file join $job routed.dcp]
