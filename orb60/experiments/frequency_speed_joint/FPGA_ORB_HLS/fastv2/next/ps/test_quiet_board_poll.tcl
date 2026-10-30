# Pure policy checks: renamed con/after point ONLY to mocks, never real hardware.
rename after quiet_test_real_after
if {[llength [info commands con]]} { rename con quiet_test_real_con }
set calls {}; set con_calls 0
# @brief Capture mock delays without sleeping.
proc after {args} { lappend ::calls $args; return MOCK_AFTER }
# @brief Capture arguments without resuming a target.
proc con {args} { incr ::con_calls; set ::con_args $args; return MOCK_CON }
source [file join [file dirname [info script]] quiet_board_poll.tcl]
next_quiet_poll_install
if {[after 250] ne "MOCK_AFTER" || [lindex $calls end] ne {250}} { error "Pre-con delay changed" }
if {[after 1000] ne "MOCK_AFTER" || [lindex $calls end] ne {1000}} { error "Reset delay changed" }
if {[con -block -timeout 7] ne "MOCK_CON" || $con_calls != 1 || $con_args ne {-block -timeout 7}} { error "con forwarding changed" }
if {[after 250] ne "MOCK_AFTER" || [lindex $calls end] ne {10000}} { error "Quiet delay missing" }
after 250 {set unused 1}
if {[lindex $calls end] ne {250 {set unused 1}}} { error "Asynchronous after changed" }
after cancel FAKE_ID
if {[lindex $calls end] ne {cancel FAKE_ID}} { error "Cancellation changed" }
if {![catch {next_quiet_poll_install}]} { error "Duplicate installation accepted" }
puts "NEXT_QUIET_POLICY_MOCK_PASS checks=7 no_JTAG=1 no_wait=1"
exit 0
