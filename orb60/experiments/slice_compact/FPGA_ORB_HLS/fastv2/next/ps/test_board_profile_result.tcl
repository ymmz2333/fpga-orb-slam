# Pure decoder/reader fixtures; all hardware names below are replaced, never forwarded.
source [file join [file dirname [info script]] board_profile_result.tcl]
set reader [file join [file dirname [info script]] read_board_profile.tcl]
set tests 0

# @brief Store exact uint64 low/high words in a fixture.
proc fixture_pair {variable offset value} {
    upvar 1 $variable words
    lset words $offset [expr {$value & 0xffffffff}]
    lset words [expr {$offset+1}] [expr {($value >> 32) & 0xffffffff}]
}

# @brief Create independent terminal fixtures; process samples are 100+i ticks.
# @param count Includes zero/1000 boundaries; outcome controls verified/unverified/failure.
proc fixture_profile {count outcome} {
    set mailbox [lrepeat 128 0]; set header [lrepeat 64 0]; set payload {}
    set production [expr {$outcome == 4}]
    set requested [expr {$count ? $count : 1}]
    foreach {offset value} [list 1 $requested 2 0x4e585452 3 5 4 $outcome 6 $count \
        9 1000000 10 100000000 11 10 12 2 26 [expr {$production?2:1}] \
        27 [expr {$production?0:$count}] 112 1 113 [expr {7*$count}] 114 1] { lset mailbox $offset $value }
    if {$outcome == 3} { lset mailbox 5 401; lset mailbox 7 $count }
    foreach {offset value} [list 0 0x4e585450 1 1 2 $outcome 3 $count 4 1000 5 1000000 \
        6 [expr {$production?2:1}] 7 1 8 32 9 64 10 0x01010100 11 4 \
        24 [lindex $mailbox 5] 25 [lindex $mailbox 7]] { lset header $offset $value }
    for {set index 0} {$index < $count} {incr index} {
        set words [lrepeat 32 0]
        set process [expr {100+$index}]; set verify [expr {$production?0:100}]
        foreach {offset value} [list 0 $process 2 [expr {$process+$verify}] 4 $verify \
            6 5 8 6 10 7 12 20 14 3 16 30 18 2 20 [expr {$production?0:1}] 22 4] {
            fixture_pair words $offset $value
        }
        foreach {offset value} [list 24 10 25 2 26 2 27 8 28 $index] { lset words $offset $value }
        set payload [concat $payload $words]
    }
    if {$count} {
        # Independent rank formulas for monotonic fixtures, not decoder output.
        set rank95 [expr {($count*95+99)/100-1}]; set rank99 [expr {($count*99+99)/100-1}]
        fixture_pair header 12 [expr {100+$rank95}]; fixture_pair header 14 [expr {100+$rank99}]
        fixture_pair header 16 [expr {100+$rank95+($production?0:100)}]
        fixture_pair header 18 [expr {100+$rank99+($production?0:100)}]
        if {$outcome != 3} {
            set average [expr {100+($count-1)/2}]
            foreach {offset value} [list 13 $average 15 [expr {$average+($production?0:100)}] \
                16 [expr {$production?0:100}] 17 2 18 20 22 100 23 [expr {100+$count-1}] \
                28 [expr {$production?0:1}] 29 3 30 30] { lset mailbox $offset $value }
        }
    }
    return [list $mailbox $header $payload $requested [expr {$production?"Production":"Verified"}]]
}

# @brief Count a deterministic check, raising on false assertions.
proc require {condition description} {
    if {!$condition} { error "Profile mock failed: $description" }
    incr ::tests
}
foreach {count outcome} {1 2 100 2 1000 2 100 4 0 3 2 3} {
    lassign [fixture_profile $count $outcome] m h p n mode
    set result [next_profile_decode $m $h $p $n $mode Pipeline]
    require [expr {[llength [dict get $result records]] == $count}] "valid prefix $count/$outcome"
    require [expr {[dict get $result outcome] eq [dict get [dict create 2 PASS 3 FAIL 4 COMPLETE_UNVERIFIED] $outcome]}] "outcome $outcome"
}
# Exact wide-word handling and percentile selection beyond signed int64.
set wide [lrepeat 2 0]; fixture_pair wide 0 0x8000000000000001
require [expr {[next_profile_ticks $wide 0] == 0x8000000000000001}] "uint64 decode"
set stats [next_profile_stats {0 0x8000000000000001}]
require [expr {[dict get $stats p95] == 0x8000000000000001}] "bignum ordering"
require [catch {next_profile_stats {0xffffffffffffffff 1}}] "overflow rejection"
require [catch {next_profile_stats {}}] "empty statistics rejection"

foreach fault {magic schema status count capacity hz mode schedule stride address reads reserved short \
    frame_index frame_reserved frame_reads frame_features frame_selected frame_candidates \
    frame_wall frame_stages frame_accounting percentile unsigned production_pass request main_average main_extrema} {
    lassign [fixture_profile 2 2] m h p n mode
    switch $fault {
        magic { lset h 0 0 }
        schema { lset h 1 99 }
        status { lset h 2 1 }
        count { lset h 3 1001 }
        capacity { lset h 4 1001 }
        hz { lset h 5 0 }
        mode { lset h 6 2 }
        schedule { lset h 7 0 }
        stride { lset h 8 31 }
        address { lset h 10 0x02000000 }
        reads { lset h 11 3 }
        reserved { lset h 63 1 }
        short { set p [lrange $p 0 end-1] }
        frame_index { lset p 28 1 }
        frame_reserved { lset p 31 1 }
        frame_reads { lset p 27 7 }
        frame_features { lset p 26 1 }
        frame_selected { lset p 25 2049 }
        frame_candidates { lset p 24 1 }
        frame_wall { lset p 2 199 }
        frame_stages { lset p 6 20 }
        frame_accounting { lset p 16 99 }
        percentile { lset h 12 999 }
        unsigned { lset p 0 -1 }
        production_pass { set mode Production; lset h 6 2; lset m 26 2 }
        request { set n 1 }
        main_average { lset m 13 99 }
        main_extrema { lset m 22 99 }
    }
    require [catch {next_profile_decode $m $h $p $n $mode Pipeline}] $fault
}

rename exit profile_mock_real_exit
rename puts profile_mock_real_puts
# @brief Convert reader exit to a catchable outcome; no OS process is terminated.
proc exit {code} { return -code error -errorcode [list PROFILE_EXIT $code] "exit $code" }
# @brief Capture all diagnostics and CSV for exact reader-output assertions.
proc puts {args} { append ::captured "[lindex $args end]\n" }
# @brief Mock connection/disconnection/selection; no real XSCT API is forwarded.
proc connect {} {}
proc disconnect {} {}
proc targets {args} {}
# @brief Supply only fixture cable and device identities.
proc jtag {args} { return $::chain_fixture }
# @brief Reject writes/programming in mocks, so regressions cannot silently add them.
foreach command {rst stop con fpga dow mwr} {
    proc $command {args} { error "FORBIDDEN_TARGET_MUTATION" }
}
# @brief Emulate bounded memory reads, including short and unstable capture faults.
proc mrd {args} {
    lassign $args option address count
    if {$option ne "-value"} { error "Unexpected mrd option" }
    incr ::read_count
    if {$address == 0x01000000} {
        set words $::m
    } elseif {$address == 0x01010000} {
        set words $::h
        if {$::fault eq "changed_header" && $::read_count > 2} { lset words 25 1 }
    } else {
        incr ::payload_reads
        set offset [expr {($address-0x01010100)/4}]
        set words [lrange $::p $offset [expr {$offset+$count-1}]]
        if {$::fault eq "changed_payload" && $::payload_reads == 2} { lset words 6 4 }
    }
    if {$::fault eq "short_read"} { return [lrange $words 0 end-1] }
    return $words
}
foreach fault {none production empty_fail prefix_fail short_read changed_header changed_payload \
    running huge_count wrong_cable wrong_device partial_commit} {
    set outcome [expr {$fault eq "production"?4:($fault in {empty_fail prefix_fail}?3:2)}]
    set count [expr {$fault eq "empty_fail"?0:2}]
    lassign [fixture_profile $count $outcome] m h p n mode
    set chain_fixture "1 Digilent JTAG-SMT2 C306ACCBABCD\n 2 xc7z015 (idcode 0373b093 irlen 6 fpga)"
    switch $fault {
        running { lset m 4 1; lset h 2 1 }
        huge_count { lset h 3 1001 }
        wrong_cable { set chain_fixture "1 Digilent JTAG-SMT2 C306ACCBABCD_OTHER\n 2 xc7z015 (idcode 0373b093)" }
        wrong_device { set chain_fixture "1 Digilent JTAG-SMT2 C306ACCBABCD\n 2 xc7z020 (idcode 03727093)" }
        partial_commit { lset h 2 1 }
    }
    set argv [list C306ACCBABCD $n $mode Pipeline]
    set captured ""; set read_count 0; set payload_reads 0
    catch {source $reader} result options
    set expected [expr {$fault in {none production}?0:2}]
    require [expr {[dict exists $options -errorcode] && [dict get $options -errorcode] eq [list PROFILE_EXIT $expected]}] "reader $fault: $result"
    if {$fault in {none production prefix_fail}} {
        require [expr {[regexp -all -line {^NEXT_PROFILE_CSV=} $captured] == $count+1}] "CSV $fault"
    }
    if {$fault in {running huge_count wrong_cable wrong_device partial_commit}} {
        require [expr {$payload_reads == 0}] "reject before payload $fault"
    }
}
profile_mock_real_puts "NEXT_PROFILE_READER_MOCK_PASS checks=$tests stable_payload=1 uint64=1 prefix=1 no_JTAG=1"
profile_mock_real_exit 0
