# Pure result validation; no connection, reset or hardware operations.
# @brief Validate a terminal mailbox against the requested ABI/mode/frame count.
# @param words Exactly 128 unsigned words read from the fixed DDR mailbox.
# @param iterations Requested timed frame count.
# @param schema Frozen firmware schema, 3, 4 or 5.
# @param mode Legacy, Verified or Production (schema 3 supports Legacy only).
# @param schedule Serial, or schema-5 Pipeline (Legacy remains serial-only).
# @return PASS, FAIL or COMPLETE_UNVERIFIED; mismatched success claims raise errors.
proc next_validate_result {words iterations schema mode {schedule Serial}} {
    if {$schema ni {3 4 5} || $mode ni {Legacy Verified Production} || $schedule ni {Serial Pipeline} ||
        ($schedule eq "Pipeline" && ($schema < 5 || $mode eq "Legacy"))} { error "Incompatible request" }
    if {[llength $words] != 128 || [lindex $words 2] != 0x4E585452 ||
        [lindex $words 3] != $schema} { error "Stale/non-next mailbox" }
    set status [lindex $words 4]
    if {$status == 3} { return FAIL }
    set production [expr {$mode eq "Production"}]
    set expected [expr {$production ? 4 : 2}]
    if {$status != $expected || [lindex $words 5] != 0 ||
        [lindex $words 6] != $iterations || [lindex $words 1] != $iterations ||
        [lindex $words 10] != 100000000} { error "Inconsistent terminal result" }
    if {$schema == 3} {
        if {$mode ne "Legacy"} { error "Schema 3 has no selectable mode" }
    } elseif {$schema >= 4} {
        set mode_id [dict get [dict create Legacy 0 Verified 1 Production 2] $mode]
        if {[lindex $words 26] != $mode_id ||
            [lindex $words 27] != ($production ? 0 : $iterations)} { error "Mode/verification mismatch" }
        if {$production && ([lindex $words 16] != 0 || [lindex $words 28] != 0 ||
            [lindex $words 24] != 0 || [lindex $words 25] != 0)} { error "Production masquerades as verified" }
    } else { error "Unsupported firmware schema" }
    if {$schema == 5} {
        set pipeline [expr {$schedule eq "Pipeline"}]
        if {[lindex $words 112] != $pipeline || [lindex $words 114] != $pipeline ||
            [lindex $words 113] != ($pipeline ? 7*$iterations : 0) ||
            [lindex $words 115] != 0 || [lindex $words 116] != 0} { error "Scheduling/ownership mismatch" }
    }
    return [expr {$production ? "COMPLETE_UNVERIFIED" : "PASS"}]
}
