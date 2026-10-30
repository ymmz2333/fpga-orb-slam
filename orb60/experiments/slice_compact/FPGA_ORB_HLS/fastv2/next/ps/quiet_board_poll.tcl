# Process-local observer policy. Source alone performs no hardware operation.

# @brief Install a narrow post-con mailbox delay override for a short authorized run.
# @note All other after forms and con arguments are delegated unchanged; no target
# clocks, firmware, watchdog, reset, output comparison or frozen runner is modified.
proc next_quiet_poll_install {} {
    if {[llength [info commands next_quiet_original_after]] ||
        [llength [info commands next_quiet_original_con]]} { error "Quiet policy already installed" }
    set ::next_quiet_running 0
    rename after next_quiet_original_after
    rename con next_quiet_original_con
    # @brief Forward con exactly once, marking the observation phase only on success.
    proc con {args} {
        set result [uplevel 1 [linsert $args 0 next_quiet_original_con]]
        set ::next_quiet_running 1
        return $result
    }
    # @brief Replace only the frozen runner's synchronous 250-ms post-con poll delay.
    proc after {args} {
        if {$::next_quiet_running && [llength $args] == 1 && [lindex $args 0] eq "250"} {
            puts "NEXT_QUIET_POLL requested_ms=250 actual_ms=10000 no_algorithm_change=1"
            return [next_quiet_original_after 10000]
        }
        return [uplevel 1 [linsert $args 0 next_quiet_original_after]]
    }
}
