# Read-only link diagnosis after an interrupted volatile board download.
# Never resets, halts, resumes, programs or writes target memory.
if {[llength $argv] != 1} { error "Expected exact Digilent JTAG-SMT2 cable serial" }
set expected_cable [lindex $argv 0]
if {[catch {
    connect
    set chain [jtag targets]
    puts $chain
    if {[string first "Digilent JTAG-SMT2 $expected_cable" $chain] < 0 ||
        [regexp -all {xc7z015 \(idcode 0373b093} $chain] != 1} {
        error "Unexpected cable/device; no target access performed"
    }
    puts [targets]
    targets -set -nocase -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    # Only allocated, existing benchmark DDR regions; repeated reads assess link
    # consistency, not algorithm correctness, voltage, or full DDR stability.
    foreach address {0x01000000 0x06400000 0x064A8000} {
        set first [mrd -value $address 1]
        set second [mrd -value $address 1]
        if {[llength $first] != 1 || $first ne $second} { error "Unstable/short read at $address" }
        puts "NEXT_LINK_READ address=$address value=$first stable=1"
    }
    puts "NEXT_LINK_READ_PASS no_target_writes=1 not_algorithm_validation=1"
    disconnect
} failure]} {
    catch {disconnect}
    puts stderr "NEXT_LINK_READ_ERROR: $failure"
    exit 2
}
exit 0
