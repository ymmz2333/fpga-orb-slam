# Offline parser tests: synthetic mrd only, no connect/JTAG/programming commands.
set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir mailbox.tcl]
set fake_words [lrepeat 128 0]
set fake_reads 0

# @brief Emulate one XSCT memory read and check exact snapshot boundaries.
# @param flag Must be -value.
# @param address Must be the fixed DDR mailbox address.
# @param count Must request all 128 words once.
# @return Synthetic unsigned-word list.
proc mrd {flag address count} {
    if {$flag ne "-value" || $address != 0x01000000 || $count != 128} {
        error "Unexpected mock read arguments"
    }
    incr ::fake_reads
    return $::fake_words
}

# @brief Fail deterministically when an offline test assertion is false.
# @param condition Boolean expression already evaluated by the caller.
# @param description Failure context.
proc require {condition description} {
    if {!$condition} { error "MAILBOX_TEST_FAIL: $description" }
}

require [expr {[fastv2mailbox::state [fastv2mailbox::read]] eq "EMPTY"}] empty
lset fake_words 1 100
lset fake_words 2 0x46563252
lset fake_words 3 2
lset fake_words 4 1
require [expr {[fastv2mailbox::state $fake_words] eq "RUNNING"}] running
lset fake_words 4 2
lset fake_words 6 100
lset fake_words 10 11078
lset fake_words 73 280
lset fake_words 25 33333
lset fake_words 26 30000
lset fake_words 11 0x89abcdef
lset fake_words 12 0x01234567
require [expr {[fastv2mailbox::u64 $fake_words 11] == 0x89abcdef01234567}] unsigned64
require [expr {[fastv2mailbox::hex64 $fake_words 11] eq "89abcdef01234567"}] hex_high_word_preserved
set read_before $fake_reads
set result [fastv2mailbox::report [fastv2mailbox::read]]
require [expr {$result eq "PASS" && $fake_reads == $read_before + 1}] single_snapshot
require [expr {[fastv2mailbox::milli 33333] eq "33.333"}] time_units
require [expr {[fastv2mailbox::milli 30000] eq "30.000"}] fps_units
lset fake_words 6 99
require [catch {fastv2mailbox::state $fake_words}] incomplete_pass_rejected
lset fake_words 6 100
lset fake_words 5 206
require [catch {fastv2mailbox::state $fake_words}] erroneous_pass_rejected
lset fake_words 4 3
require [expr {[fastv2mailbox::state $fake_words] eq "FAIL"}] fail
lset fake_words 2 0x4f524652
require [catch {fastv2mailbox::state $fake_words}] baseline_magic_rejected
lset fake_words 2 0x46563252
lset fake_words 3 1
require [catch {fastv2mailbox::state $fake_words}] old_schema_rejected
set fake_words [lrepeat 127 0]
require [catch {fastv2mailbox::read}] short_read_rejected
foreach filename {build_sdk.tcl run_board_benchmark.tcl check_board_result.tcl} {
    set source_file [open [file join $script_dir $filename] r]
    set body [read $source_file]
    close $source_file
    require [info complete $body] "$filename incomplete Tcl source"
}
puts "FASTV2_MAILBOX_TEST_PASS (offline synthetic data, not board measurements)"
