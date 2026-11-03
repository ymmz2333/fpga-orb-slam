# Shared complete-top reporting after route or post-route refinement.
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
report_exceptions -summary -file [file join $job exceptions_summary.rpt]
set f [open [file join $job routed_audit.tsv] w]
puts $f "part\t[get_property PART [current_design]]"
puts $f "vivado\t[version -short]"
puts $f "black_box_count\t[llength [get_cells -hierarchical -quiet -filter {IS_BLACKBOX == 1}]]"
foreach clk [get_clocks] {puts $f "clock\t$clk\t[get_property PERIOD $clk]"}
set errors 0; set critical 0; set warnings 0
foreach v [get_drc_violations -quiet] {
    switch -- [get_property SEVERITY $v] {Error {incr errors} {Critical Warning} {incr critical} Warning {incr warnings}}
}
puts $f "drc_errors\t$errors"
puts $f "drc_critical_warnings\t$critical"
puts $f "drc_warnings\t$warnings"
close $f
write_hw_platform -fixed -force -file [file join $job kv260_dpu_points.xsa]
puts "DPU_ONLY_ROUTE_REPORTS_COMPLETE_NOT_BOARD_VERIFIED"
exit
