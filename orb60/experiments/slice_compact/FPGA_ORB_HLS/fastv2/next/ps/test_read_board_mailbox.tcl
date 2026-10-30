# Exercise the snapshot reader with Tcl-only mocks; never invokes real JTAG APIs.
set reader [file join [file dirname [info script]] read_board_mailbox.tcl]
rename exit mock_snapshot_real_exit
rename puts mock_snapshot_real_puts
# @brief Convert terminal exit into a catchable test result.
proc exit {code} { return -code error -errorcode [list SNAPSHOT_EXIT $code] "exit $code" }
# @brief Capture diagnostics for assertions without forwarding target operations.
proc puts {args} { append ::captured "[lindex $args end]\n" }
# @brief Mock connection; no call reaches the original programmer.
proc connect {} {}
# @brief Mock disconnection; no call reaches the original programmer.
proc disconnect {} {}
# @brief Return the test cable/device chain, never real hardware.
proc jtag {args} { return $::chain_fixture }
# @brief Mock debug-target selection without changing an actual target.
proc targets {args} {}
# @brief Return either stable or faulted mock DDR reads.
proc mrd {args} {
    incr ::read_count
    set words $::word_fixture
    if {$::fault eq "short"} { return [lrange $words 0 126] }
    if {$::fault eq "changed" && $::read_count == 2} { lset words 24 1 }
    return $words
}
set tests 0
foreach fault {none short changed magic running schema cable device} {
    set word_fixture [lrepeat 128 0]
    foreach {index value} {2 0x4E585452 3 5 4 2 6 100} { lset word_fixture $index $value }
    set chain_fixture "1 Digilent JTAG-SMT2 C306ACCBABCD\n 2 xc7z015 (idcode 0373b093 irlen 6 fpga)"
    switch $fault {
        magic { lset word_fixture 2 0 }
        running { lset word_fixture 4 1 }
        schema { lset word_fixture 3 99 }
        cable { set chain_fixture "1 Digilent JTAG-SMT2 DIFFERENT\n 2 xc7z015 (idcode 0373b093 irlen 6 fpga)" }
        device { set chain_fixture "1 Digilent JTAG-SMT2 C306ACCBABCD\n 2 xc7z020 (idcode 03727093 irlen 6 fpga)" }
    }
    set argv {C306ACCBABCD}; set captured ""; set read_count 0
    catch {source $reader} result options
    set expected [expr {$fault eq "none" ? 0 : 2}]
    if {![dict exists $options -errorcode] || [dict get $options -errorcode] ne [list SNAPSHOT_EXIT $expected]} {
        error "Snapshot mock failed: $fault $result"
    }
    if {$fault eq "none" && [string first "NEXT_MAILBOX_WORDS=" $captured] < 0} { error "Missing complete capture" }
    incr tests
}
mock_snapshot_real_puts "NEXT_MAILBOX_READER_MOCK_PASS cases=$tests no_JTAG=1"
mock_snapshot_real_exit 0
