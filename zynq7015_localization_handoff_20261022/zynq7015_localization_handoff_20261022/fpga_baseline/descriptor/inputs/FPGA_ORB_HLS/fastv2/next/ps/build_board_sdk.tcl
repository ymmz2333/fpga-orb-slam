# Build only a fresh SDK workspace owned by the calling isolated next board job.
if {![info exists ::env(NEXT_BOARD_ROOT)]} { error "Use next/scripts/build_board.ps1" }
set root [file normalize $::env(NEXT_BOARD_ROOT)]
set workspace [file join $root sdk]
set inputs [file join $root inputs]
set hardware [file join $root vivado next_system_wrapper.hdf]
if {[file exists $workspace]} { error "Refusing to overwrite an existing SDK workspace" }
set base_sources {board_benchmark.c board_pipeline.inc board_contract.h next_backend.c next_backend.h backend_tables.h front_reference.inc full_reference.inc}
set profile_sources {board_profile_sdk.c backend_profile_sdk.c board_profile.inc board_profile_contract.h next_backend_profile.h next_frame_stats.c next_frame_stats.h}
set profile [file isfile [file join $inputs board_profile_sdk.c]]
set sources $base_sources
if {$profile} { set sources [concat $sources $profile_sources] }
foreach name $profile_sources {
    if {!$profile && [file exists [file join $inputs $name]]} { error "Partial Profile inputs in default build: $name" }
}
foreach name $sources {
    if {![file isfile [file join $inputs $name]]} { error "Missing frozen PS input: $name" }
}
if {![file isfile $hardware]} { error "Missing routed next hardware export" }
file mkdir $workspace
setws $workspace
createhw -name next_hw -hwspec $hardware
createbsp -name next_bsp -hwproject next_hw -proc ps7_cortexa9_0 -os standalone
createapp -name next_benchmark -hwproject next_hw -proc ps7_cortexa9_0 \
    -os standalone -lang C -app {Empty Application} -bsp next_bsp
foreach name $sources {
    # Profile's sole main() comes from its explicit wrapper, not two C entries.
    set compiled_name $name
    if {$profile && $name eq "board_benchmark.c"} { set compiled_name board_benchmark_source.inc }
    file copy [file join $inputs $name] [file join $workspace next_benchmark src $compiled_name]
}
configapp -app next_benchmark compiler-optimization {Optimize more (-O2)}
projects -build -type bsp -name next_bsp
projects -build -type app -name next_benchmark
set executable [file join $workspace next_benchmark Debug next_benchmark.elf]
if {![file isfile $executable]} { error "Missing compiled next benchmark ELF" }
set stamp [open [file join $workspace .sdk_success] w]
puts $stamp NEXT_BOARD_SDK_PASS
close $stamp
puts "NEXT_BOARD_SDK_PASS elf=$executable"
if {$profile} {
    set stamp [open [file join $workspace .profile_sdk_success] w]
    puts $stamp NEXT_BOARD_PROFILE_SDK_PASS
    close $stamp
    puts "NEXT_BOARD_PROFILE_SDK_PASS separate_app=1 default_off=1 elf=$executable"
}
