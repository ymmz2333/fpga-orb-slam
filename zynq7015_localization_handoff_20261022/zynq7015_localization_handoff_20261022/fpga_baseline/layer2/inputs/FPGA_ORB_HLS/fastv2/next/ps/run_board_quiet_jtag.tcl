# Authorized SRAM/DDR test with reduced observer interference, not a background job.
# Caller MUST first validate this explicit job with run_board.ps1 -ArtifactsOnly.
if {[llength $argv] != 4} { error "Expected paired job, 1..100 frames, mode, schedule" }
lassign $argv accepted_root iterations mode schedule
if {![string is integer -strict $iterations] || $iterations < 1 || $iterations > 100 ||
    $mode ni {Verified Production} || $schedule ni {Serial Pipeline} ||
    ![file isfile [file join $accepted_root inputs run_board.tcl]]} { error "Invalid quiet run request" }
source [file join [file dirname [info script]] quiet_board_poll.tcl]
next_quiet_poll_install
# Unmodified slow adapter setup and accepted frozen runner retain exact acceptance.
# First result read is delayed ten seconds; if not yet terminal, its existing
# deadline still applies and subsequent reads are ten seconds apart. This does
# not guarantee no interference for a run that takes more than ten seconds.
source [file join [file dirname [info script]] run_board_slow_jtag.tcl]
