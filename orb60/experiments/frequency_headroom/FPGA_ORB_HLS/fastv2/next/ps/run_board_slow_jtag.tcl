# One explicitly authorized volatile run of an accepted frozen board runner.
# Reduce only the adapter clock, never FPGA clocks/RTL or numerical acceptance.
# Calling PowerShell must first run run_board.ps1 -ArtifactsOnly for this job.
if {[llength $argv] != 4} { error "Expected accepted job, iterations, mode, schedule" }
set accepted_root [file normalize [lindex $argv 0]]
set frozen_runner [file join $accepted_root inputs run_board.tcl]
if {![file isfile $frozen_runner]} { error "Missing accepted frozen runner" }
if {[catch {
    connect
    set chain [jtag targets]
    if {[string first "Digilent JTAG-SMT2 C306ACCBABCD" $chain] < 0 ||
        [regexp -all {xc7z015 \(idcode 0373b093} $chain] != 1} { error "Unexpected cable/device" }
    jtag targets -set -filter {name =~ "*C306ACCBABCD*"}
    set before [jtag frequency]
    set supported [jtag frequency -list]
    if {[lsearch -exact $supported 1000000] < 0} { error "Adapter does not advertise 1 MHz: $supported" }
    set after [jtag frequency 1000000]
    if {$after != 1000000} { error "Adapter did not accept requested 1 MHz" }
    puts "NEXT_JTAG_FREQUENCY before_hz=$before after_hz=$after device=xc7z015 cable=C306ACCBABCD"
    disconnect
} failure]} {
    catch {disconnect}
    puts stderr "NEXT_SLOW_JTAG_SETUP_ERROR: $failure"
    exit 2
}
# Frequency persists only for this hw_server lifetime. No repeat loop is added;
# the unchanged frozen runner performs its own validated terminal-result check.
source $frozen_runner
