# SDK 2018.3 build; only the explicitly bounded fastv2 workspace is regenerated.
set script_dir [file dirname [file normalize [info script]]]
set project_root [file normalize [file join $script_dir .. ..]]
set workspace [file join $project_root sdk_build_fastv2]
set hardware_spec [file join $project_root vivado_build_fastv2 fastv2_system_wrapper.hdf]
foreach required [list $hardware_spec [file join $script_dir fastv2_benchmark.c] \
    [file join $script_dir fastv2_reference.inc]] {
    if {![file exists $required]} { error "Missing fastv2 build input: $required" }
}
# Never accept a caller-supplied recursive deletion target.
if {[file normalize $workspace] ne [file normalize [file join $project_root sdk_build_fastv2]]} {
    error "Unsafe generated workspace path"
}
if {[file exists $workspace]} { file delete -force $workspace }
file mkdir $workspace
setws $workspace
createhw -name fastv2_hw -hwspec $hardware_spec
createbsp -name fastv2_bsp -hwproject fastv2_hw -proc ps7_cortexa9_0 -os standalone
createapp -name fastv2_benchmark -hwproject fastv2_hw -proc ps7_cortexa9_0 \
    -os standalone -lang C -app {Empty Application} -bsp fastv2_bsp
foreach filename {fastv2_benchmark.c fastv2_reference.inc} {
    file copy -force [file join $script_dir $filename] \
        [file join $workspace fastv2_benchmark src $filename]
}
puts "=== FASTV2_OPTIMIZATION_OPTIONS ==="
puts [configapp -app fastv2_benchmark -info compiler-optimization]
configapp -app fastv2_benchmark compiler-optimization {Optimize more (-O2)}
projects -build -type bsp -name fastv2_bsp
projects -build -type app -name fastv2_benchmark
set executable [file join $workspace fastv2_benchmark Debug fastv2_benchmark.elf]
if {![file exists $executable]} { error "Missing compiled fastv2 ELF: $executable" }
set stamp [open [file join $workspace .sdk_success] w]
puts $stamp "FASTV2_SDK_BUILD_SUCCESS"
close $stamp
puts "FASTV2_SDK_BUILD_PASS elf=$executable"
