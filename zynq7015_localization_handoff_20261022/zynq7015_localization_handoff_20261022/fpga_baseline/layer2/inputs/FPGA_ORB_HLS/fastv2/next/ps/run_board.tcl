# SRAM-only JTAG benchmark. Never writes flash, SD, eFUSE or persistent configuration.
if {[llength $argv] < 2 || [llength $argv] > 4} { error "Expected board job, iterations, optional mode and schedule" }
set root [file normalize [lindex $argv 0]]
set iterations [lindex $argv 1]
source [file join [file dirname [info script]] board_result.tcl]
set contract_file [open [file join $root inputs board_contract.h] r]
set contract [read $contract_file]
close $contract_file
if {![regexp {NEXT_SCHEMA\s*=\s*([345])\s*,} $contract -> schema]} { error "Unsupported frozen schema" }
set mode [expr {$schema == 3 ? "Legacy" : "Verified"}]
if {[llength $argv] >= 3} { set mode [lindex $argv 2] }
if {$mode ni {Legacy Verified Production} || ($schema == 3 && $mode ne "Legacy")} { error "Mode incompatible with firmware" }
set mode_id [dict get [dict create Legacy 0 Verified 1 Production 2] $mode]
set schedule Serial
if {[llength $argv] == 4} { set schedule [lindex $argv 3] }
if {$schedule ni {Serial Pipeline} || ($schedule eq "Pipeline" && ($schema < 5 || $mode eq "Legacy"))} {
    error "Schedule incompatible with firmware/mode"
}
set schedule_id [expr {$schedule eq "Pipeline"}]
if {![string is integer -strict $iterations] || $iterations < 1 || $iterations > 1000} { error "Expected 1..1000 frames" }
set init [file join $root sdk next_hw ps7_init.tcl]
set bit [file join $root vivado next_fpga.runs impl_1 next_system_wrapper.bit]
set elf [file join $root sdk next_benchmark Debug next_benchmark.elf]
foreach path [list $init $bit $elf [file join $root inputs input.pgm] \
    [file join $root inputs reference_raw.bin] [file join $root inputs reference_blur.bin]] {
    if {![file isfile $path]} { error "Missing paired board artifact: $path" }
}
# @brief Read one complete 512-byte mailbox; caller decides polling policy.
# @return Exactly 128 unsigned 32-bit words.
proc next_mailbox_read {} {
    set raw [mrd -value 0x01000000 128]
    if {[llength $raw] != 128} { error "Short next mailbox read" }
    set words {}
    foreach word $raw { lappend words [expr {$word & 0xffffffff}] }
    return $words
}
# @brief Format microseconds as milliseconds or milli-FPS as FPS.
# @param value Unsigned fixed-point value scaled by 1000.
proc next_milli {value} { return [format "%d.%03d" [expr {$value / 1000}] [expr {$value % 1000}]] }
if {[catch {
    connect
    set chain [jtag targets]
    puts $chain
    if {[regexp -all {xc7z015 \(idcode 0373b093} $chain] != 1} { error "Expected one xc7z015 JTAG device" }
    targets -set -nocase -filter {name =~ "APU"}
    rst -system
    after 1000
    targets -set -nocase -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    source $init
    ps7_init
    fpga -file $bit
    ps7_post_config
    ps7_debug
    dow $elf
    dow -data [file join $root inputs input.pgm] 0x02000000
    dow -data [file join $root inputs reference_raw.bin] 0x06000000
    dow -data [file join $root inputs reference_blur.bin] 0x06400000
    mwr 0x01000008 0
    mwr 0x01000010 0
    mwr 0x01000000 0x4E585443
    mwr 0x01000004 $iterations
    if {$schema >= 4} { mwr 0x01000068 $mode_id }
    if {$schema == 5} { mwr 0x010001C0 $schedule_id }
    con
    set deadline [expr {[clock milliseconds] + 60000 + 5000 * $iterations}]
    set status 0
    while {[clock milliseconds] < $deadline} {
        after 250
        set words [next_mailbox_read]
        if {[lindex $words 2] == 0} { continue }
        if {[lindex $words 2] != 0x4E585452 || [lindex $words 3] != $schema} { error "Stale/non-next mailbox" }
        set status [lindex $words 4]
        if {$status == 2 || $status == 3 || $status == 4} { break }
    }
    stop
    if {$status ni {2 3 4}} { error "Next board mailbox timeout" }
    set outcome [next_validate_result $words $iterations $schema $mode $schedule]
    puts [format "NEXT_BOARD_STATUS=%s error=%d completed=%d/%d detail=%08x" \
        $outcome [lindex $words 5] [lindex $words 6] $iterations [lindex $words 8]]
    puts "schema=$schema mode=$mode schedule=$schedule"
    if {$schema == 5} {
        puts "backend_ahead_launches=[lindex $words 113] pl_observation_upper_bound=[lindex $words 114] abort_drain_error=[lindex $words 115] pending_core_mask=[lindex $words 116]"
        if {$schedule eq "Pipeline"} { puts "PL_OBSERVATION_UPPER_BOUNDS: PS polling is deferred during descriptors; not true PL cycles" }
    }
    if {$schema >= 4} {
        puts [format "verified_frames=%d poison_fill_ms=%s cache_ms=%s pl_wait_ms=%s other_ms=%s min_ms=%s max_ms=%s" \
            [lindex $words 27] [next_milli [lindex $words 28]] [next_milli [lindex $words 29]] \
            [next_milli [lindex $words 30]] [next_milli [lindex $words 31]] \
            [next_milli [lindex $words 22]] [next_milli [lindex $words 23]]]
        if {$mode eq "Production"} { puts "UNVERIFIED_TIMING_ONLY: no per-frame CPU comparison or poison/guard checks" }
    }
    puts [format "processing_ms=%s fps=%s wall_ms=%s verification_ms=%s config_ms=%s backend_ms=%s" \
        [next_milli [lindex $words 13]] [next_milli [lindex $words 14]] \
        [next_milli [lindex $words 15]] [next_milli [lindex $words 16]] \
        [next_milli [lindex $words 17]] [next_milli [lindex $words 18]]]
    puts [format "front_sum_ms=%s resize_sum_ms=%s gaussian_sum_ms=%s candidates=%d features=%d" \
        [next_milli [lindex $words 19]] [next_milli [lindex $words 20]] \
        [next_milli [lindex $words 21]] [lindex $words 11] [lindex $words 12]]
    for {set level 0} {$level < 8} {incr level} {
        if {$schema >= 4} {
            puts [format "level=%d poison_fill_ms=%s cache_ms=%s pl_wait_ms=%s" $level \
                [next_milli [lindex $words [expr {88+$level}]]] \
                [next_milli [lindex $words [expr {96+$level}]]] \
                [next_milli [lindex $words [expr {104+$level}]]]]
        }
        puts [format "level=%d front_ms=%s resize_ms=%s gaussian_ms=%s ps_backend_ms=%s" $level \
            [next_milli [lindex $words [expr {32+$level}]]] \
            [next_milli [lindex $words [expr {40+$level}]]] \
            [next_milli [lindex $words [expr {48+$level}]]] \
            [next_milli [lindex $words [expr {56+$level}]]]]
        puts [format "level=%d PS_observed_equivalent_cycles front=%d resize=%d gaussian=%d" $level \
            [lindex $words [expr {64+$level}]] [lindex $words [expr {72+$level}]] \
            [lindex $words [expr {80+$level}]]]
    }
    disconnect
    if {$outcome eq "FAIL"} { error "Next complete-frame run failed" }
} failure]} {
    catch {stop}
    catch {disconnect}
    puts stderr "NEXT_BOARD_ERROR: $failure"
    exit 2
}
exit 0
