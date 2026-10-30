# Pure SDK-generation mocks: no SDK project build, hardware connection or JTAG.
if {[llength $argv]!=1} { error "Expected a new diagnostic directory" }
set sdk_test_root [file normalize [lindex $argv 0]]
if {[file exists $sdk_test_root]} { error "Refusing to overwrite diagnostic directory" }
file mkdir $sdk_test_root
set sdk_builder [file join [file dirname [info script]] build_board_sdk.tcl]
set sdk_base_names {board_benchmark.c board_pipeline.inc board_contract.h next_backend.c next_backend.h backend_tables.h front_reference.inc full_reference.inc}
set sdk_extra_names {board_profile_sdk.c backend_profile_sdk.c board_profile.inc board_profile_contract.h next_backend_profile.h next_frame_stats.c next_frame_stats.h}
# @brief Create dummy fixture data owned by this test, never source/accepted jobs.
proc sdk_test_write {path value} {
    file mkdir [file dirname $path]
    set channel [open $path w]; puts $channel $value; close $channel
}
# @brief Fail deterministically on a wrong mapping or unexpectedly accepted input.
proc sdk_test_require {valid message} { if {!$valid} { error $message } }
# @brief Mock every SDK command used by the builder; none calls original APIs.
proc setws {path} { set ::sdk_mock_workspace $path }
proc createhw {args} { incr ::sdk_mock_calls }
proc createbsp {args} { incr ::sdk_mock_calls }
proc createapp {args} {
    incr ::sdk_mock_calls
    file mkdir [file join $::sdk_mock_workspace next_benchmark src]
}
proc configapp {args} {
    sdk_test_require [expr {$args eq {-app next_benchmark compiler-optimization {Optimize more (-O2)}}}] "Wrong optimization/app"
}
proc projects {args} {
    incr ::sdk_mock_calls
    if {[lsearch -exact $args app]>=0} {
        sdk_test_write [file join $::sdk_mock_workspace next_benchmark Debug next_benchmark.elf] MOCK_NOT_ARM_ELF
    }
}
set sdk_test_cases 0
foreach variant {normal profile} {
    set ::env(NEXT_BOARD_ROOT) [file join $sdk_test_root $variant]
    foreach name $sdk_base_names { sdk_test_write [file join $::env(NEXT_BOARD_ROOT) inputs $name] "fixture-$name" }
    if {$variant eq "profile"} {
        foreach name $sdk_extra_names { sdk_test_write [file join $::env(NEXT_BOARD_ROOT) inputs $name] "fixture-$name" }
    }
    sdk_test_write [file join $::env(NEXT_BOARD_ROOT) vivado next_system_wrapper.hdf] MOCK_NOT_HDF
    set ::sdk_mock_calls 0
    source $sdk_builder
    sdk_test_require [expr {$::sdk_mock_calls==5}] "Wrong mocked SDK command count"
    set src [file join $::env(NEXT_BOARD_ROOT) sdk next_benchmark src]
    if {$variant eq "profile"} {
        sdk_test_require [expr {![file exists [file join $src board_benchmark.c]] &&
            [file isfile [file join $src board_benchmark_source.inc]] &&
            [file isfile [file join $::env(NEXT_BOARD_ROOT) sdk .profile_sdk_success]]}] "Profile main/stamp mapping failed"
        foreach name $sdk_extra_names { sdk_test_require [file isfile [file join $src $name]] "Missing Profile copied source" }
    } else {
        sdk_test_require [expr {[file isfile [file join $src board_benchmark.c]] &&
            ![file exists [file join $src board_benchmark_source.inc]] &&
            ![file exists [file join $::env(NEXT_BOARD_ROOT) sdk .profile_sdk_success]]}] "Default build contaminated"
    }
    incr sdk_test_cases
    set code [catch {source $sdk_builder} message]
    sdk_test_require [expr {$code && [string match {*Refusing to overwrite*} $message]}] "Existing SDK was not rejected"
    incr sdk_test_cases
}
foreach missing $sdk_extra_names {
    set ::env(NEXT_BOARD_ROOT) [file join $sdk_test_root "missing-$missing"]
    foreach name [concat $sdk_base_names $sdk_extra_names] {
        if {$name ne $missing} { sdk_test_write [file join $::env(NEXT_BOARD_ROOT) inputs $name] fixture }
    }
    sdk_test_write [file join $::env(NEXT_BOARD_ROOT) vivado next_system_wrapper.hdf] MOCK_NOT_HDF
    set ::sdk_mock_calls 0
    set code [catch {source $sdk_builder} message]
    sdk_test_require [expr {$code && $::sdk_mock_calls==0 && ![file exists [file join $::env(NEXT_BOARD_ROOT) sdk]]}] "Partial Profile sources accepted"
    incr sdk_test_cases
}
puts "NEXT_PROFILE_SDK_MAPPING_MOCK_PASS cases=$sdk_test_cases default=1 profile=1 partial_rejected=7 overwrite_rejected=2 hardware_actions=0 mock_not_sdk_build=1"
