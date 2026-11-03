# Re-open the full routed checkpoint; emit machine-readable coverage/DRC facts.
set job [file normalize $::env(KV260_UNIFIED_JOB)]
open_checkpoint [file join $job routed.dcp]
report_exceptions -summary -file [file join $job exceptions_summary.rpt]
set f [open [file join $job routed_audit.tsv] w]
puts $f "part\t[get_property PART [current_design]]"
puts $f "vivado\t[version -short]"
puts $f "black_box_count\t[llength [get_cells -hierarchical -quiet -filter {IS_BLACKBOX == 1}]]"
foreach clk [get_clocks] {puts $f "clock\t$clk\t[get_property PERIOD $clk]"}
report_drc -file [file join $job drc_audit.rpt]
set errors 0;set critical 0;set warnings 0
foreach v [get_drc_violations -quiet] {
    set severity [get_property SEVERITY $v]
    if {$severity eq "Error"} {incr errors}
    if {$severity eq "Critical Warning"} {incr critical}
    if {$severity eq "Warning"} {incr warnings}
}
puts $f "drc_errors\t$errors"
puts $f "drc_critical_warnings\t$critical"
puts $f "drc_warnings\t$warnings"
close $f
exit
