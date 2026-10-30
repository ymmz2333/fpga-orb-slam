# Volatile JTAG benchmark. Execute only after explicit hardware authorization.
# Does not modify QSPI, SD, eFUSE or any nonvolatile board configuration.
set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir mailbox.tcl]
set project_root [file normalize [file join $script_dir .. ..]]
set bitstream [file join $project_root vivado_build_fastv2 fastv2_fpga.runs impl_1 fastv2_system_wrapper.bit]
set workspace [file join $project_root sdk_build_fastv2]
set init_script [file join $workspace fastv2_hw ps7_init.tcl]
set executable [file join $workspace fastv2_benchmark Debug fastv2_benchmark.elf]
set input_file [file join $project_root .. FPGA_ORB_SHARED_v1.0 vectors flight_20261004T184929_998838_6bb93c56_f0000 input.pgm]
set reference_file [file join $script_dir reference_pyramid.bin]
set iterations 100
if {[llength $argv] == 1} { set iterations [lindex $argv 0] }
if {[llength $argv] > 1 || ![string is integer -strict $iterations] || $iterations < 1 || $iterations > 1000} {
    puts stderr "Expected iteration count from 1 through 1000"
    exit 2
}
foreach required [list $bitstream $init_script $executable $input_file $reference_file] {
    if {![file isfile $required]} { puts stderr "Missing artifact: $required"; exit 2 }
}
if {[catch {
    connect
    set chain [jtag targets]
    puts $chain
    if {![string match "*xc7z015 (idcode 0373b093*" $chain]} {
        error "Expected xc7z015 JTAG device not found"
    }
    targets -set -nocase -filter {name =~ "APU"}
    rst -system
    after 1000
    targets -set -nocase -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    source $init_script
    ps7_init
    fpga -file $bitstream
    ps7_post_config
    ps7_debug
    dow $executable
    dow -data $input_file 0x02000000
    dow -data $reference_file 0x06000000
    mwr 0x01000008 0
    mwr 0x01000010 0
    mwr 0x01000000 0x46563243
    mwr 0x01000004 $iterations
    con
    set deadline [expr {[clock milliseconds] + 60000 + 5000 * $iterations}]
    set result RUNNING
    set last_completed -1
    while {[clock milliseconds] < $deadline} {
        after 250
        set words [fastv2mailbox::read]
        set result [fastv2mailbox::state $words]
        set completed [lindex $words 6]
        if {$completed != $last_completed && $result ne "EMPTY"} {
            puts "progress=$completed/$iterations"
            set last_completed $completed
        }
        if {$result eq "PASS" || $result eq "FAIL"} { break }
    }
    catch {stop}
    if {$result ne "PASS" && $result ne "FAIL"} { error "fastv2 mailbox timeout" }
    fastv2mailbox::report [fastv2mailbox::read]
    disconnect
    if {$result ne "PASS"} { error "fastv2 self-test failed" }
} failure]} {
    catch {stop}
    catch {disconnect}
    puts stderr "FASTV2_BOARD_ERROR: $failure"
    exit 2
}
exit 0
