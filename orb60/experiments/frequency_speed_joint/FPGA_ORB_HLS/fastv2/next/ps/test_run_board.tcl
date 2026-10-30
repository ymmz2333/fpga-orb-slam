# Execute the runner against Tcl-only programmer mocks; never touch JTAG.
if {[llength $argv] != 1} { error "Expected completed board fixture job" }
set fixture [file normalize [lindex $argv 0]]
set runner [file join [file dirname [info script]] run_board.tcl]
set f [open [file join $fixture inputs board_contract.h] r]
set header [read $f]; close $f
if {![regexp {NEXT_SCHEMA\s*=\s*([345])\s*,} $header -> fixture_schema]} { error "Wrong fixture" }
rename source mock_real_source
rename puts mock_real_puts
rename exit mock_real_exit
# @brief Load pure scripts normally, but suppress the fixture's hardware initialization.
proc source {path} {
    if {[file tail $path] eq "ps7_init.tcl"} { return }
    uplevel 1 [list mock_real_source $path]
}
# @brief Capture runner diagnostics without changing its status validation.
proc puts {args} { append ::captured "[lindex $args end]\n" }
# @brief Turn the runner's exit into an exception caught by this test harness.
proc exit {code} { return -code error -errorcode [list MOCK_EXIT $code] "mock exit $code" }
# @brief Mock a programmer command; none forwards to the original XSCT API.
proc connect {} { incr ::connections }
proc jtag {args} { return "1 Digilent JTAG-SMT2 MOCK\n 2 xc7z015 (idcode 0373b093 irlen 6 fpga)" }
proc targets {args} {}
proc rst {args} {}
proc ps7_init {} {}
proc fpga {args} {}
proc ps7_post_config {} {}
proc ps7_debug {} {}
proc dow {args} {}
proc stop {} {}
proc disconnect {} {}
proc after {args} {}
# @brief Record command mailbox writes, not physical memory writes.
proc mwr {address value} { dict set ::writes [expr {$address}] $value }
# @brief Return one deterministic terminal result instead of reading a device.
proc mrd {args} { return $::mock_words }
# @brief Require the runner to program a complete request before resuming.
proc con {} {
    if {[dict get $::writes [expr {0x01000000}]] != 0x4E585443 || [dict get $::writes [expr {0x01000004}]] != 100} {
        error "Missing frame command"
    }
    if {$::fixture_schema >= 4 && [dict get $::writes [expr {0x01000068}]] != $::expected_mode} { error "Missing mode command" }
    if {$::fixture_schema == 5 && [dict get $::writes [expr {0x010001C0}]] != $::expected_schedule} { error "Missing schedule command" }
}
set cases [expr {$fixture_schema == 3 ? {Legacy} : {Legacy Verified Production}}]
set tests 0
foreach selected_mode $cases {
    set expected_mode [dict get [dict create Legacy 0 Verified 1 Production 2] $selected_mode]
    set schedules [expr {$fixture_schema == 5 && $selected_mode ne "Legacy" ? {Serial Pipeline} : {Serial}}]
    foreach selected_schedule $schedules {
    set expected_schedule [expr {$selected_schedule eq "Pipeline"}]
    foreach bad {0 1} {
        set mock_words [lrepeat 128 0]
        foreach {index value} [list 1 100 2 0x4E585452 3 $fixture_schema 4 [expr {$selected_mode eq "Production" ? 4 : 2}] \
            6 100 10 100000000 26 $expected_mode 27 [expr {$selected_mode eq "Production" ? 0 : 100}]] {
            lset mock_words $index $value
        }
        if {$fixture_schema == 5} {
            foreach {index value} [list 112 $expected_schedule 113 [expr {700*$expected_schedule}] 114 $expected_schedule] {
                lset mock_words $index $value
            }
        }
        if {$bad} { lset mock_words 6 99 }
        set writes {}; set captured ""; set connections 0
        set argv [list $fixture 100 $selected_mode]
        if {$fixture_schema == 5} { lappend argv $selected_schedule }
        catch {source $runner} result options
        set expected_exit [expr {$bad ? 2 : 0}]
        if {![dict exists $options -errorcode] || [dict get $options -errorcode] ne [list MOCK_EXIT $expected_exit] || $connections != 1} {
            error "Runner fixture failed: mode=$selected_mode schedule=$selected_schedule bad=$bad $result; output=$captured"
        }
        if {!$bad} {
            set expected_label [expr {$selected_mode eq "Production" ? "COMPLETE_UNVERIFIED" : "PASS"}]
            if {[string first "NEXT_BOARD_STATUS=$expected_label " $captured] < 0} { error "Wrong terminal output" }
        }
        incr tests
    }
    }
}
set writes {}; set captured ""; set connections 0
set argv [list $fixture 100 Legacy Pipeline]
if {![catch {source $runner}] || $connections != 0} { error "Incompatible schedule reached JTAG mock" }
mock_real_puts "NEXT_RUNNER_MOCK_PASS schema=$fixture_schema cases=$tests no_JTAG=1"
mock_real_exit 0
