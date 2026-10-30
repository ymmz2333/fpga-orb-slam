# Read-only terminal-result capture for the explicitly selected ACZ7015 cable.
# Never resets, resumes, halts, programs or writes any target memory.
if {[llength $argv] != 1} { error "Expected exact Digilent JTAG-SMT2 cable serial" }
set expected_cable [lindex $argv 0]
# @brief Read and normalize one complete next DDR result block.
# @return Exactly 128 unsigned words, without changing target state.
proc next_snapshot_words {} {
    set raw [mrd -value 0x01000000 128]
    if {[llength $raw] != 128} { error "Short mailbox snapshot" }
    set words {}
    foreach value $raw { lappend words [expr {$value & 0xffffffff}] }
    return $words
}
if {[catch {
    connect
    set chain [jtag targets]
    if {[string first "Digilent JTAG-SMT2 $expected_cable" $chain] < 0 ||
        [regexp -all {xc7z015 \(idcode 0373b093} $chain] != 1} { error "Unexpected cable/device" }
    puts $chain
    targets -set -nocase -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    set words [next_snapshot_words]
    if {$words ne [next_snapshot_words]} { error "Mailbox changed during snapshot" }
    if {[lindex $words 2] != 0x4E585452 || [lindex $words 3] ni {3 4 5} ||
        [lindex $words 4] ni {2 3 4}} { error "Not a terminal next result" }
    puts "NEXT_MAILBOX_WORDS=$words"
    puts [format "NEXT_MAILBOX_DIGEST=%08x%08x schema=%d status=%d completed=%d" \
        [lindex $words 24] [lindex $words 25] [lindex $words 3] \
        [lindex $words 4] [lindex $words 6]]
    disconnect
} failure]} {
    catch {disconnect}
    puts stderr "NEXT_MAILBOX_SNAPSHOT_ERROR: $failure"
    exit 2
}
exit 0
