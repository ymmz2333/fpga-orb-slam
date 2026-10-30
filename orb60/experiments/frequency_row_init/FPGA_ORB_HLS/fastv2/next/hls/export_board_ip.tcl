# Export only cloned, already synthesized solutions; never reopen an active RTL job.
if {![info exists ::env(NEXT_EXPORT_PROJECT)] || ![info exists ::env(NEXT_EXPORT_STAMP)]} {
    error "Use the isolated next board worker"
}
if {[catch {
    # HLS 2018.3 expects a project name, not an unnormalized Windows path.
    # Require the cloned project to exist; open_project must not create a new one.
    set project_path [file normalize [string map {\\ /} $::env(NEXT_EXPORT_PROJECT)]]
    if {![file isdirectory $project_path] || ![file exists [file join $project_path vivado_hls.app]]} {
        error "Missing cloned HLS project: $project_path"
    }
    cd [file dirname $project_path]
    open_project [file tail $project_path]
    open_solution solution1
    export_design -rtl verilog -format ip_catalog
    close_project
} failure]} { puts stderr "NEXT_BOARD_EXPORT_FAILED: $failure"; exit 1 }
set stamp [open $::env(NEXT_EXPORT_STAMP) w]
puts $stamp NEXT_BOARD_EXPORT_SUCCESS
close $stamp
exit 0
