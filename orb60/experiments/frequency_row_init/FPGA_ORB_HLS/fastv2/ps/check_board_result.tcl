# One read-only result query. Never programs, resets, stops, or resumes a core.
source [file join [file dirname [file normalize [info script]]] mailbox.tcl]
if {[catch {
    connect
    set chain [jtag targets]
    if {![string match "*xc7z015 (idcode 0373b093*" $chain]} {
        error "Expected xc7z015 target not found"
    }
    targets -set -nocase -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    fastv2mailbox::report [fastv2mailbox::read]
    disconnect
} failure]} {
    catch {disconnect}
    puts stderr "FASTV2_READ_ERROR: $failure"
    exit 2
}
