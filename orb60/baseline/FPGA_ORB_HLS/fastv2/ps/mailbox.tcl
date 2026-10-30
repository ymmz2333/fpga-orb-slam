# fastv2 schema-2 fixed DDR mailbox. Loading this file never connects or writes.
namespace eval fastv2mailbox { variable base 0x01000000 }

# @brief Read a single snapshot without stopping, resetting, or programming PS/PL.
# @return Exactly 128 unsigned words from the 512-byte mailbox.
proc fastv2mailbox::read {} {
    variable base
    set raw [mrd -value $base 128]
    if {[llength $raw] != 128} { error "Short mailbox read: [llength $raw] words" }
    set words {}
    foreach word $raw { lappend words [expr {$word & 0xffffffff}] }
    return $words
}

# @brief Validate mailbox identity, terminal state and completion consistency.
# @param words Snapshot returned by read.
# @return EMPTY, RUNNING, PASS or FAIL; inconsistent or stale layouts raise errors.
proc fastv2mailbox::state {words} {
    if {[llength $words] != 128} { error "Invalid mailbox snapshot length" }
    if {[lindex $words 2] == 0} { return EMPTY }
    if {[lindex $words 2] != 0x46563252 || [lindex $words 3] != 2} {
        error "Mailbox is not fastv2 schema 2; refuse baseline/stale result"
    }
    set status [lindex $words 4]
    if {$status < 0 || $status > 3} { error "Invalid mailbox status: $status" }
    set name [lindex {EMPTY RUNNING PASS FAIL} $status]
    if {$name eq "PASS" && ([lindex $words 5] != 0 ||
        [lindex $words 1] < 1 || [lindex $words 1] > 1000 ||
        [lindex $words 6] != [lindex $words 1])} {
        error "Inconsistent PASS: error code or completed/requested mismatch"
    }
    return $name
}

# @brief Format an integer scaled by 1000 with three decimal places.
# @param value Nonnegative integer microseconds or milli-FPS.
# @return Milliseconds or FPS decimal string, respectively.
proc fastv2mailbox::milli {value} {
    return [format "%d.%03d" [expr {$value / 1000}] [expr {$value % 1000}]]
}

# @brief Assemble a high-word/low-word unsigned 64-bit value.
# @param words Validated snapshot.
# @param index Index of the high word.
# @return Unsigned 64-bit value.
proc fastv2mailbox::u64 {words index} {
    return [expr {([lindex $words $index] << 32) | [lindex $words [expr {$index + 1}]]}]
}

# @brief Format two unsigned words without Tcl 8.5 percent-x 32-bit truncation.
# @param words Validated snapshot.
# @param index Index of the high word.
# @return Exactly 16 hexadecimal digits.
proc fastv2mailbox::hex64 {words index} {
    return [format "%08x%08x" [lindex $words $index] [lindex $words [expr {$index + 1}]]]
}

# @brief Print core, pipeline, verification, wall and per-level measurements.
# @param words One snapshot; no additional hardware reads are performed.
# @return Validated mailbox state.
proc fastv2mailbox::report {words} {
    set name [state $words]
    puts [format "status=%s error_code=%d completed=%d requested=%d failing_iteration=%d detail=%08x" \
        $name [lindex $words 5] [lindex $words 6] [lindex $words 1] \
        [lindex $words 7] [lindex $words 32]]
    if {$name eq "EMPTY" || $name eq "RUNNING"} { return $name }
    puts [format "candidates=%d selected=%d selected_digest=%s image_digest=%s" \
        [lindex $words 10] [lindex $words 73] [hex64 $words 11] [hex64 $words 13]]
    foreach {label index} {front 15 resize 20} {
        puts [format "%s_config_ms=%s %s_wait_ms=%s min_ms=%s max_ms=%s fps=%s" \
            $label [milli [lindex $words $index]] $label \
            [milli [lindex $words [expr {$index + 1}]]] \
            [milli [lindex $words [expr {$index + 2}]]] \
            [milli [lindex $words [expr {$index + 3}]]] \
            [milli [lindex $words [expr {$index + 4}]]]]
    }
    puts [format "pipeline_ms=%s pipeline_fps=%s min_ms=%s max_ms=%s verification_ms=%s wall_ms=%s wall_fps=%s total_ms=%s" \
        [milli [lindex $words 25]] [milli [lindex $words 26]] \
        [milli [lindex $words 114]] [milli [lindex $words 115]] \
        [milli [lindex $words 27]] [milli [lindex $words 28]] \
        [milli [lindex $words 29]] [milli [u64 $words 30]]]
    puts "cycle_kind=PS_observed_equivalent_100MHz_including_AXI_and_polling_not_internal_counter"
    for {set level 0} {$level < 8} {incr level} {
        puts [format "level=%d candidates=%d selected=%d selected_digest=%s front_ms=%s resize_ms=%s front_elapsed_cycles=%s resize_elapsed_cycles=%s" \
            $level [lindex $words [expr {33 + $level}]] \
            [lindex $words [expr {74 + $level}]] [hex64 $words [expr {41 + 2 * $level}]] \
            [milli [lindex $words [expr {57 + $level}]]] \
            [milli [lindex $words [expr {65 + $level}]]] \
            [u64 $words [expr {82 + 2 * $level}]] \
            [u64 $words [expr {98 + 2 * $level}]]]
    }
    return $name
}
