# Explicitly authorized, read-only terminal Profile capture; no retry or polling.
# No rst/stop/con/fpga/dow/mwr or nonvolatile operations occur in this file.
source [file join [file dirname [info script]] board_profile_result.tcl]
if {[llength $argv] != 4} { error "Expected exact cable serial, iterations, mode, schedule" }
lassign $argv expected_cable iterations mode schedule
if {![regexp {^[A-Za-z0-9]+$} $expected_cable] ||
    ![string is integer -strict $iterations] || $iterations < 1 || $iterations > 1000 ||
    $mode ni {Legacy Verified Production} || $schedule ni {Serial Pipeline}} { error "Invalid snapshot request" }

# @brief Read only a bounded allocated region and normalize XSCT word values.
# @param address Fixed mailbox/Profile address, count 1..256 words per transaction.
proc next_profile_read_words {address count} {
    if {$count < 1 || $count > 256 || !($address == 0x01000000 && $count == 128) &&
        !($address >= 0x01010000 && $address+$count*4 <= 0x0102f500)} { error "Out-of-region Profile read" }
    set raw [mrd -value [format 0x%08x $address] $count]
    if {[llength $raw] != $count} { error "Short Profile DDR read" }
    set words {}
    foreach word $raw { lappend words [expr {$word & 0xffffffff}] }
    return $words
}

# @brief Capture one terminal prefix, bounded by its validated header, with bookends.
# @return Mailbox/header/payload list only if both metadata bookends are unchanged.
proc next_profile_snapshot {iterations mode schedule} {
    set mailbox [next_profile_read_words 0x01000000 128]
    set header [next_profile_read_words 0x01010000 64]
    set count [next_profile_validate_header $mailbox $header $iterations $mode $schedule]
    set payload {}
    for {set offset 0} {$offset < $count*32} {incr offset 256} {
        set chunk [expr {min(256,$count*32-$offset)}]
        set payload [concat $payload [next_profile_read_words [expr {0x01010100+$offset*4}] $chunk]]
    }
    if {$header ne [next_profile_read_words 0x01010000 64] ||
        $mailbox ne [next_profile_read_words 0x01000000 128]} { error "Profile metadata changed during capture" }
    return [list $mailbox $header $payload]
}

if {[catch {
    connect
    set chain [jtag targets]
    if {[regexp -all "Digilent JTAG-SMT2 ${expected_cable}(?:\\s|$)" $chain] != 1 ||
        [regexp -all {xc7z015 \(idcode 0373b093} $chain] != 1} { error "Unexpected cable/device" }
    puts $chain
    targets -set -nocase -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    set first [next_profile_snapshot $iterations $mode $schedule]
    set second [next_profile_snapshot $iterations $mode $schedule]
    if {$first ne $second} { error "Profile payload changed between snapshots" }
    lassign $first mailbox header payload
    set decoded [next_profile_decode $mailbox $header $payload $iterations $mode $schedule]
    puts "NEXT_PROFILE_MAILBOX_WORDS=$mailbox"
    puts "NEXT_PROFILE_HEADER_WORDS=$header"
    next_profile_print $decoded
    puts "NEXT_PROFILE_STABLE_CAPTURE no_target_writes=1 source_identity_requires_paired_run_log=1"
    disconnect
    if {[dict get $decoded outcome] eq "FAIL"} { error "Algorithm FAIL; prefix is diagnostic only" }
} failure]} {
    catch {disconnect}
    puts stderr "NEXT_PROFILE_SNAPSHOT_ERROR: $failure"
    exit 2
}
exit 0
