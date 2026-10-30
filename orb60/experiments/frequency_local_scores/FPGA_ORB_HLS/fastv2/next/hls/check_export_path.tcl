# Regression for the authored exporter without packaging IP or changing hardware.
# Invoke with the process-isolated SDK xsct Tcl interpreter.
set script_root [file dirname [file normalize [info script]]]
set temporary_root [file normalize [file join $script_root .. board_build path_check_[pid]]]
file mkdir [file join $temporary_root projects next_front]
set project_marker [open [file join $temporary_root projects next_front vivado_hls.app] w]
puts $project_marker {mock project: not a synthesized artifact}
close $project_marker
set ::env(NEXT_EXPORT_PROJECT) [string map {/ \\} [file join $temporary_root projects next_front]]
set ::env(NEXT_EXPORT_STAMP) [file join $temporary_root mock.success]

# @brief Check that the exporter passes only the existing project basename.
# @param name Project name passed to the HLS command.
proc open_project {name} {
    if {$name ne "next_front" || [file tail [pwd]] ne "projects"} {
        error "Exporter used an absolute project name or wrong working directory"
    }
}
# @brief Check the frozen HLS solution name.
# @param name Selected solution.
proc open_solution {name} { if {$name ne "solution1"} { error "Wrong solution" } }
# @brief Check the unchanged IP format and RTL language without generating outputs.
# @param args HLS export options.
proc export_design {args} {
    if {$args ne {-rtl verilog -format ip_catalog}} { error "Wrong export options" }
}
# @brief Mock closing the HLS project.
proc close_project {} {}
# @brief Turn exporter exits into an inspectable return value for this test.
# @param code Requested process status.
rename exit native_exit
proc exit {code} { return -code error "EXPORT_TEST_EXIT=$code" }
catch {source [file join $script_root export_board_ip.tcl]} result
if {$result ne "EXPORT_TEST_EXIT=0" || ![file exists $::env(NEXT_EXPORT_STAMP)]} {
    puts stderr "NEXT_EXPORT_PATH_FAIL: $result"
    native_exit 1
}
puts "NEXT_EXPORT_PATH_PASS windows_backslash_path=PASS relative_project_name=PASS"
native_exit 0
