# Read-only diagnosis of a failed candidate. Never emit a release XSA/bitstream.
set job [file normalize $::env(KV260_UNIFIED_JOB)]
set out [file join $job failure_diagnostics]
file mkdir $out
set_param general.maxThreads 4
open_checkpoint $::env(KV260_FAILED_DCP)
report_route_status -file [file join $out route_status.rpt]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out utilization_hierarchical.rpt]
report_design_analysis -congestion -file [file join $out congestion.rpt]
report_timing_summary -check_timing_verbose -report_unconstrained -file [file join $out timing_summary.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $out setup_paths.rpt]
report_drc -file [file join $out drc.rpt]
puts "FAILED_ROUTE_DIAGNOSTICS_COMPLETE_NOT_A_RELEASE"
exit
