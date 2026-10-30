# Pure Tcl regression: no design open, synthesis, implementation or JTAG.
source [file join [file dirname [info script]] timing_checks.tcl]
if {[llength $argv] != 1} { error "Provide a completed 2018.3 check_timing report" }
set input [open [lindex $argv 0] r]
set report [read $input]
close $input
next_check_timing_coverage $report

# @brief Require that invalid coverage reports are rejected, never silently waived.
# @param name Fault case label.
# @param report Mutated report retaining its table of contents.
proc expect_rejection {name report} {
    if {![catch {next_check_timing_coverage $report} reason]} {
        error "Timing checker accepted invalid report: $name"
    }
    puts "NEXT_TIMING_CHECK_REJECT_PASS case=$name reason=$reason"
}
set bad_clock [string map {{There are 0 register/latch pins with no clock.} {There are 1 register/latch pins with no clock.}} $report]
set bad_endpoints [string map {{There are 0 pins that are not constrained for maximum delay.} {There are 2 pins that are not constrained for maximum delay.}} $report]
set missing_count [string map {{There are 0 register/latch pins with no clock.} {Count unavailable.}} $report]
if {$bad_clock eq $report || $bad_endpoints eq $report || $missing_count eq $report} {
    error "Fault injection did not match the actual report"
}
expect_rejection no_clock $bad_clock
expect_rejection unconstrained_internal_endpoints $bad_endpoints
expect_rejection missing_count $missing_count
expect_rejection empty_report {}
puts NEXT_TIMING_CHECK_PASS
exit 0
