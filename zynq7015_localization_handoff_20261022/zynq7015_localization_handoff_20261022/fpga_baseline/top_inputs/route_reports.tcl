# Shared strict post-route evidence for new builds and checkpoint recovery.
proc orb60_report_routed {build_dir part_name fabric_frequency front_top timing_only {scope "complete three-core routed top; protocol/board acceptance pending"}} {
    file mkdir $build_dir
    report_utilization -file [file join $build_dir post_route_utilization.rpt]
    report_utilization -hierarchical -file [file join $build_dir post_route_hierarchy.rpt]
    report_design_analysis -congestion -file [file join $build_dir post_route_congestion.rpt]
    report_route_status -file [file join $build_dir post_route_route_status.rpt]
    report_drc -file [file join $build_dir post_route_drc.rpt]
    report_methodology -file [file join $build_dir post_route_methodology.rpt]
    write_checkpoint [file join $build_dir next_system_routed.dcp]
    report_timing_summary -check_timing_verbose -report_unconstrained -file [file join $build_dir post_route_timing.rpt]
    report_timing -delay_type max -max_paths 20 -nworst 3 -file [file join $build_dir post_route_setup_paths.rpt]
    report_timing -delay_type min -max_paths 10 -nworst 2 -file [file join $build_dir post_route_hold_paths.rpt]
    check_timing -verbose -file [file join $build_dir post_route_check_timing.rpt]
    set worst_setup [get_timing_paths -delay_type max -max_paths 1]
    set worst_hold [get_timing_paths -delay_type min -max_paths 1]
    if {[llength $worst_setup] == 0 || [llength $worst_hold] == 0} {error "Missing routed timing paths"}
    set summary_file [open [file join $build_dir post_route_timing.rpt] r]
    set summary_metrics [next_timing_summary_metrics [read $summary_file]];close $summary_file
    set metrics [open [file join $build_dir post_route_metrics.tsv] w]
    puts $metrics "scope\t$scope"
    puts $metrics "part\t$part_name"
    puts $metrics "frequency_mhz\t$fabric_frequency"
    puts $metrics "front_top\t$front_top"
    puts $metrics "wns_ns\t[get_property SLACK $worst_setup]"
    puts $metrics "whs_ns\t[get_property SLACK $worst_hold]"
    dict for {name value} $summary_metrics {puts $metrics "$name\t$value"}
    foreach property {DATAPATH_DELAY LOGIC_LEVELS STARTPOINT_PIN ENDPOINT_PIN REQUIREMENT} {
        puts $metrics "setup_$property\t[get_property $property $worst_setup]"
    }
    close $metrics
    puts "ORB60_ROUTED_TIMING WNS=[get_property SLACK $worst_setup] WHS=[get_property SLACK $worst_hold]"
    if {[info exists ::env(ORB60_ROUTE_DIAGNOSTICS)] && $::env(ORB60_ROUTE_DIAGNOSTICS) eq "1"} {
        source [file join [file dirname [info script]] diagnostic_reports.tcl]
        orb60_diagnostic_reports [file join $build_dir post_route_diagnostics]
    }
    set f [open [file join $build_dir post_route_route_status.rpt] r]
    set routing [read $f]; close $f
    foreach {name pattern} {
        routable {# of routable nets[. \t]*:[ \t]*([0-9]+)}
        routed {# of fully routed nets[. \t]*:[ \t]*([0-9]+)}
        errors {# of nets with routing errors[. \t]*:[ \t]*([0-9]+)}
    } {
        if {![regexp $pattern $routing unused value]} {error "Missing route-status count: $name"}
        set route_counts($name) $value
    }
    if {$route_counts(routable) != $route_counts(routed) || $route_counts(errors) != 0} {error "Incomplete or erroneous routing"}
    set f [open [file join $build_dir post_route_check_timing.rpt] r]
    set checks_text [read $f]; close $f
    next_check_timing_coverage $checks_text
    if {[dict get $summary_metrics tns_ns] != 0 || [dict get $summary_metrics ths_ns] != 0 ||
        [dict get $summary_metrics setup_failed_endpoints] != 0 || [dict get $summary_metrics hold_failed_endpoints] != 0} {
        error "Nonzero routed total negative slack or failing endpoints"
    }
    if {[get_property SLACK $worst_setup] < 0 || [get_property SLACK $worst_hold] < 0} {error "Routed setup/hold timing failed; inspect retained path reports"}
    foreach violation [get_drc_violations -quiet] {
        if {[get_property SEVERITY $violation] in {Error {Critical Warning}}} {error "Unresolved routed DRC: $violation"}
    }
    if {!$timing_only} {write_hw_platform -fixed -include_bit -force -file [file join $build_dir next_system_wrapper.xsa]}
    set stamp_name .vivado_success
    set pass_message NEXT_BOARD_VIVADO_BUILD_SUCCESS
    if {$timing_only} {set stamp_name .vivado_timing_success; set pass_message ORB60_TIMING_PASS}
    set stamp [open [file join $build_dir $stamp_name] w]
    puts $stamp $pass_message; close $stamp
    puts $pass_message
}
