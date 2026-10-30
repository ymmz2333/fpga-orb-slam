# @brief Validate clock coverage from the Vivado verbose report body.
# @param report Complete check_timing report text, not its table of contents.
# @return Two validated zero counts; errors on missing sections or nonzero counts.
proc next_check_timing_coverage {report} {
    set checks {
        no_clock {register/latch pins with no clock\.}
        unconstrained_internal_endpoints {pins that are not constrained for maximum delay\.}
    }
    set counts {}
    foreach {category sentence} $checks {
        # The section heading must be followed by its divider and count sentence.
        # This excludes the identically named table-of-contents entry.
        set pattern [format {(?m)^[0-9]+\.[ \t]+checking %s(?:[ \t]+\(([0-9]+)\))?[ \t]*\r?\n-+\r?\n[ \t]*There are ([0-9]+) %s} $category $sentence]
        if {![regexp $pattern $report unused heading_count count]} {
            error "Cannot validate routed timing coverage for $category; review the check_timing report"
        }
        if {$heading_count ne "" && $heading_count != $count} {error "Inconsistent timing coverage counts for $category"}
        if {$count != 0} { error "Unresolved routed timing coverage: $category=$count" }
        lappend counts $category $count
    }
    return $counts
}

# Parse the aggregate design table, excluding per-clock/path-group tables.
proc next_timing_summary_metrics {report} {
    set pattern {(?m)^[ \t]*WNS\(ns\)[ \t]+TNS\(ns\)[^\r\n]*\r?\n[ \t-]+\r?\n[ \t]*([-+]?[0-9]+\.[0-9]+)[ \t]+([-+]?[0-9]+\.[0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]+([-+]?[0-9]+\.[0-9]+)[ \t]+([-+]?[0-9]+\.[0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]+([-+]?[0-9]+\.[0-9]+)[ \t]+([-+]?[0-9]+\.[0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]*$}
    if {![regexp $pattern $report unused wns tns setup_failed setup_total whs ths hold_failed hold_total wpws tpws pulse_failed pulse_total]} {
        error "Missing aggregate timing-summary metrics"
    }
    return [dict create summary_wns_ns $wns tns_ns $tns setup_failed_endpoints $setup_failed setup_total_endpoints $setup_total \
        summary_whs_ns $whs ths_ns $ths hold_failed_endpoints $hold_failed hold_total_endpoints $hold_total \
        wpws_ns $wpws tpws_ns $tpws pulse_failed_endpoints $pulse_failed pulse_total_endpoints $pulse_total]
}
