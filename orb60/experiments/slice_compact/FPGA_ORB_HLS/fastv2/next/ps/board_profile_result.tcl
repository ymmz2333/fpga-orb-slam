# Pure schema-1 Profile decoder. No connection, memory access or target mutation.
source [file join [file dirname [info script]] board_result.tcl]

# @brief Require an exact array of unsigned 32-bit words before decoding offsets.
# @param words Tcl list from a normalized read or an offline fixture.
# @param count Expected bounded word count.
proc next_profile_words_check {words count} {
    if {[llength $words] != $count} { error "Short Profile word array" }
    foreach word $words {
        if {![string is wideinteger -strict $word] || $word < 0 || $word > 0xffffffff} {
            error "Invalid unsigned Profile word"
        }
    }
}

# @brief Decode a little-endian uint64 tick pair without floating-point rounding.
# @return Exact nonnegative Tcl integer, including values above signed int64.
proc next_profile_ticks {words offset} {
    return [expr {[lindex $words $offset] | ([lindex $words [expr {$offset+1}]] << 32)}]
}

# @brief Order exact tick values, including Tcl bignums, for nearest-rank statistics.
proc next_profile_tick_compare {left right} {
    return [expr {$left < $right ? -1 : ($left > $right ? 1 : 0)}]
}

# @brief Compute exact total/min/max/P95/P99; caller converts units after validation.
# @param samples Between one and 1000 unsigned uint64 tick samples.
# @return Dictionary; uint64 total overflow raises an error like the firmware.
proc next_profile_stats {samples} {
    set count [llength $samples]
    if {$count < 1 || $count > 1000} { error "Invalid Profile statistics count" }
    set total 0
    foreach value $samples {
        if {$value < 0 || $value > 0xffffffffffffffff} { error "Invalid Profile ticks" }
        set total [expr {$total+$value}]
        if {$total > 0xffffffffffffffff} { error "Profile statistics overflow" }
    }
    set sorted [lsort -command next_profile_tick_compare $samples]
    return [dict create total $total min [lindex $sorted 0] max [lindex $sorted end] \
        p95 [lindex $sorted [expr {($count*95+99)/100-1}]] \
        p99 [lindex $sorted [expr {($count*99+99)/100-1}]] count $count]
}

# @brief Validate bounded terminal metadata BEFORE allocating/reading frame payload.
# @param mailbox Schema-5 result, header Private schema-1 result, iterations/mode/schedule request.
# @return Committed complete-frame prefix count; FAIL is not algorithm acceptance.
proc next_profile_validate_header {mailbox header iterations mode schedule} {
    next_profile_words_check $mailbox 128
    next_profile_words_check $header 64
    if {![string is integer -strict $iterations] || $iterations < 1 || $iterations > 1000 ||
        $mode ni {Legacy Verified Production} || $schedule ni {Serial Pipeline} ||
        ($mode eq "Legacy" && $schedule eq "Pipeline")} { error "Invalid Profile request" }
    set mode_id [dict get [dict create Legacy 0 Verified 1 Production 2] $mode]
    set schedule_id [expr {$schedule eq "Pipeline"}]
    set status [lindex $mailbox 4]
    set count [lindex $header 3]
    if {[lindex $mailbox 2] != 0x4e585452 || [lindex $mailbox 3] != 5 || $status ni {2 3 4} ||
        [lindex $mailbox 1] != $iterations || [lindex $mailbox 10] != 100000000 ||
        [lindex $mailbox 26] != $mode_id || [lindex $mailbox 112] != $schedule_id ||
        [lindex $header 0] != 0x4e585450 || [lindex $header 1] != 1 ||
        [lindex $header 2] != $status || [lindex $header 4] != 1000 ||
        [lindex $header 5] == 0 || [lindex $header 5] != [lindex $mailbox 9] ||
        [lindex $header 6] != $mode_id || [lindex $header 7] != $schedule_id ||
        [lindex $header 8] != 32 || [lindex $header 9] != 64 ||
        [lindex $header 10] != 0x01010100 || [lindex $header 11] != 4 ||
        [lindex $header 24] != [lindex $mailbox 5] ||
        [lindex $header 25] != [lindex $mailbox 7] ||
        $count > 1000 || $count > $iterations || $count != [lindex $mailbox 6]} {
        error "Stale/inconsistent Profile header/mailbox"
    }
    set reserved {20 21 22 23}
    for {set offset 26} {$offset < 64} {incr offset} { lappend reserved $offset }
    foreach offset $reserved {
        if {[lindex $header $offset] != 0} { error "Nonzero Profile reserved header" }
    }
    if {$mode eq "Production" && ($status == 2 || [lindex $mailbox 27] != 0 ||
        [lindex $mailbox 24] != 0 || [lindex $mailbox 25] != 0)} { error "Production masquerades as PASS" }
    if {$status == 3} {
        if {[lindex $mailbox 5] == 0 || [lindex $mailbox 27] > $count} { error "Invalid Profile failure prefix" }
        if {!$count && ([next_profile_ticks $header 12] || [next_profile_ticks $header 14] ||
            [next_profile_ticks $header 16] || [next_profile_ticks $header 18])} { error "Stale empty-prefix percentiles" }
    } else {
        next_validate_result $mailbox $iterations 5 $mode $schedule
        if {!$count} { error "Empty successful Profile" }
    }
    return $count
}

# @brief Validate every committed frame and firmware percentiles using exact raw ticks.
# @return Dictionary with outcome/records/stats/hz; never promotes Production or FAIL.
proc next_profile_decode {mailbox header payload iterations mode schedule} {
    set count [next_profile_validate_header $mailbox $header $iterations $mode $schedule]
    next_profile_words_check $payload [expr {$count*32}]
    set names {process wall verify moments cordic brief backend cache wait config prep clock_calibration}
    set values [dict create]
    foreach name $names { dict set values $name {} }
    set records {}
    for {set index 0} {$index < $count} {incr index} {
        set words [lrange $payload [expr {$index*32}] [expr {$index*32+31}]]
        set record [dict create index $index]
        set offset 0
        foreach name $names {
            set ticks [next_profile_ticks $words $offset]
            dict set record $name $ticks
            dict lappend values $name $ticks
            incr offset 2
        }
        set selected [lindex $words 25]
        if {[lindex $words 28] != $index || [lindex $words 29] != 0 ||
            [lindex $words 30] != 0 || [lindex $words 31] != 0 || $selected > 2048 ||
            [lindex $words 24] < $selected || [lindex $words 26] != $selected ||
            [lindex $words 27] != 4*$selected ||
            [dict get $record process]+[dict get $record verify] != [dict get $record wall] ||
            [dict get $record moments]+[dict get $record cordic]+[dict get $record brief] > [dict get $record backend] ||
            [dict get $record backend]+[dict get $record cache]+[dict get $record wait]+[dict get $record config]+[dict get $record prep] > [dict get $record process] ||
            ($mode eq "Production" && ([dict get $record verify] || [dict get $record prep]))} {
            error "Invalid Profile frame $index"
        }
        foreach {name offset} {candidates 24 selected 25 features 26 clock_reads 27} {
            dict set record $name [lindex $words $offset]
        }
        lappend records $record
    }
    set stats [dict create]
    if {$count} {
        foreach name $names { dict set stats $name [next_profile_stats [dict get $values $name]] }
        foreach {name percentile offset} {process p95 12 process p99 14 wall p95 16 wall p99 18} {
            if {[dict get $stats $name $percentile] != [next_profile_ticks $header $offset]} {
                error "Profile percentile mismatch $name/$percentile"
            }
        }
        if {[lindex $mailbox 4] != 3 &&
            ([dict get [lindex $records end] candidates] != [lindex $mailbox 11] ||
             [dict get [lindex $records end] selected] != [lindex $mailbox 12])} { error "Last frame counters mismatch" }
        if {[lindex $mailbox 4] != 3} {
            # Match firmware integer averaging followed by rounded microseconds.
            set hz [lindex $header 5]
            foreach {name offset} {process 13 wall 15 verify 16 config 17 backend 18 prep 28 cache 29 wait 30} {
                set average [expr {[dict get $stats $name total]/$count}]
                set expected [expr {($average*1000000+$hz/2)/$hz}]
                if {$expected != [lindex $mailbox $offset]} { error "Profile/main average mismatch $name" }
            }
            foreach {stat offset} {min 22 max 23} {
                set expected [expr {([dict get $stats process $stat]*1000000+$hz/2)/$hz}]
                if {$expected != [lindex $mailbox $offset]} { error "Profile/main extrema mismatch $stat" }
            }
        }
    }
    set outcome [dict get [dict create 2 PASS 3 FAIL 4 COMPLETE_UNVERIFIED] [lindex $mailbox 4]]
    return [dict create outcome $outcome records $records stats $stats hz [lindex $header 5]]
}

# @brief Emit exact raw CSV and real PS timer statistics, with no calibration subtraction.
# @note CSV is stdout only; caller saves logs. FAIL-prefix times are not accepted FPS.
proc next_profile_print {decoded} {
    set names {process wall verify moments cordic brief backend cache wait config prep clock_calibration}
    puts "NEXT_PROFILE_RESULT=[dict get $decoded outcome] frames=[llength [dict get $decoded records]] timer_hz=[dict get $decoded hz] calibration_not_deducted=1"
    puts "NEXT_PROFILE_CSV=index,[join $names _ticks,]_ticks,candidates,selected,features,clock_reads"
    foreach record [dict get $decoded records] {
        set row [list [dict get $record index]]
        foreach name [concat $names {candidates selected features clock_reads}] { lappend row [dict get $record $name] }
        puts "NEXT_PROFILE_CSV=[join $row ,]"
    }
    foreach name $names {
        if {![dict exists $decoded stats $name]} { continue }
        set stats [dict get $decoded stats $name]
        set scale [expr {1000.0/[dict get $decoded hz]}]
        puts [format "NEXT_PROFILE_METRIC metric=%s mean_ms=%.6f min_ms=%.6f max_ms=%.6f p95_ms=%.6f p99_ms=%.6f" \
            $name [expr {[dict get $stats total]*$scale/[dict get $stats count]}] \
            [expr {[dict get $stats min]*$scale}] [expr {[dict get $stats max]*$scale}] \
            [expr {[dict get $stats p95]*$scale}] [expr {[dict get $stats p99]*$scale}]]
    }
}
