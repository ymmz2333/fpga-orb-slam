# Bounded post-route optimization of a retained complete DPU-only design.
# All clocks, timing exceptions and DPU parameters come unchanged from the DCP.
set root [file normalize $::env(FPGA_PROJECT_ROOT)]
set job [file normalize $::env(KV260_DPU_ONLY_JOB)]
set base [file normalize $::env(KV260_DPU_ONLY_BASE)]
set_param general.maxThreads 4
cd $job
open_checkpoint [file join $base routed.dcp]
phys_opt_design -directive AggressiveExplore
set worst [get_timing_paths -quiet -delay_type max -max_paths 1]
if {[llength $worst] && [get_property SLACK $worst] < 0} {
    route_design -tns_cleanup
}
source [file join [file dirname [file normalize [info script]]] report_dpu_only.tcl]
