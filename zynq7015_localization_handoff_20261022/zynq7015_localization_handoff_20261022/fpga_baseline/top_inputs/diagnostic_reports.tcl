# Read-only diagnostics for a loaded routed design. No constraints, placement,
# RTL, checkpoints or original reports are changed by this procedure.
proc orb60_diagnostic_reports {directory} {
    file mkdir $directory
    set paths [get_timing_paths -delay_type max -max_paths 200 -nworst 1 -sort_by slack]
    if {[llength $paths] != 200} {error "Expected 200 distinct-endpoint setup paths"}
    # Path selection is already frozen in $paths. Vivado 2024.2 rejects
    # -max_paths with -of_objects; do not apply selection options twice.
    # This build also ignores -path_type with -of_objects. Export the exact
    # selected objects and let the parser bound the actual data-path rows.
    report_timing -of_objects $paths -file [file join $directory setup_200.rpt]
    puts "ORB60_DIAGNOSTIC_STAGE setup_exported paths=[llength $paths]"
    report_high_fanout_nets -max_nets 50 -timing -load_types -file [file join $directory high_fanout_50.rpt]
    report_control_sets -verbose -sort_by {clk clkEn set} -file [file join $directory control_sets.rpt]
    report_control_sets -verbose -hierarchical -file [file join $directory control_sets_hierarchy.rpt]
    puts "ORB60_DIAGNOSTIC_STAGE fanout_and_control_sets_exported"
    set f [open [file join $directory paths.tsv] w]
    puts $f "index\tslack_ns\tlogic_levels\tdatapath_ns\tstartpoint\tendpoint"
    set endpoints {}; set index 0
    foreach path $paths {
        set endpoint [get_property ENDPOINT_PIN $path]
        if {[dict exists $endpoints $endpoint]} {error "Repeated setup endpoint: $endpoint"}
        dict set endpoints $endpoint 1
        puts $f "$index\t[get_property SLACK $path]\t[get_property LOGIC_LEVELS $path]\t[get_property DATAPATH_DELAY $path]\t[get_property STARTPOINT_PIN $path]\t$endpoint"
        incr index
    }
    close $f

    # Rank actual leaf-load fanout; collapse aliases of one physical net by
    # their leaf drivers. Clock fanout is kept separate from reset/CE/data.
    set ranked {}
    foreach net [get_nets -hierarchical -filter {FLAT_PIN_COUNT > 1}] {
        lappend ranked [list [get_property FLAT_PIN_COUNT $net] $net]
    }
    set ranked [lsort -integer -decreasing -index 0 $ranked]
    set f [open [file join $directory nets.tsv] w]
    puts $f "net\tfanout\tclock_loads\treset_loads\tce_loads\tdata_loads\tload_resources\tdrivers\tslack_ns\ttiming_scope"
    set drivers_seen {}; set count 0
    foreach item $ranked {
        set net [lindex $item 1]
        set segments [get_nets -segments $net]
        set drivers [get_pins -leaf -of_objects $segments -filter {DIRECTION == OUT}]
        set identity [join [lsort $drivers] {;}]
        if {$identity eq ""} {set identity [join [lsort [get_ports -of_objects $segments -filter {DIRECTION == IN}]] {;}]}
        if {$identity eq ""} {set identity "undriven:[get_property NAME $net]"}
        if {[dict exists $drivers_seen $identity]} {continue}
        dict set drivers_seen $identity 1
        set loads [get_pins -leaf -of_objects $segments -filter {DIRECTION == IN}]
        if {[llength $loads] == 0} {error "High-fanout net has no leaf loads: $net"}
        set classes [dict create clock 0 reset 0 ce 0 data 0]
        set resources {}
        foreach pin $loads {
            set refpin [file tail [get_property NAME $pin]]
            set cell [get_cells -of_objects $pin]
            set ref [get_property REF_NAME $cell]
            dict incr resources $ref
            set class data
            if {$refpin in {C CLK CLKA CLKB CLKARDCLK CLKBWRCLK ACLK} ||
                ([string match BUFG* $ref] && $refpin in {I I0 I1})} {
                set class clock
            } elseif {$refpin in {R S CLR PRE} || [string match RST* $refpin]} {
                set class reset
            } elseif {[string match CE* $refpin] || [string match REGCE* $refpin] || $refpin in {EN ENA ENB ENARDEN ENBWREN}} {
                set class ce
            }
            dict incr classes $class
        }
        set timing_scope no_constrained_data_path; set slack NA
        if {[dict get $classes clock] == [llength $loads]} {
            set timing_scope clock_distribution
        } else {
            set timing [get_timing_paths -delay_type max -through $net -max_paths 1]
            if {[llength $timing]} {set slack [get_property SLACK $timing];set timing_scope constrained_data_path}
        }
        set resource_text {}
        foreach ref [lsort [dict keys $resources]] {lappend resource_text "${ref}:[dict get $resources $ref]"}
        puts $f "[get_property NAME $net]\t[llength $loads]\t[dict get $classes clock]\t[dict get $classes reset]\t[dict get $classes ce]\t[dict get $classes data]\t[join $resource_text {;}]\t$identity\t$slack\t$timing_scope"
        incr count
        if {$count == 50} {break}
    }
    close $f
    if {$count != 50} {error "Expected 50 distinct physical high-fanout nets"}
    set metadata [open [file join $directory design.tsv] w]
    puts $metadata "part\t[get_property PART [current_design]]"
    puts $metadata "paths\t[llength $paths]"
    puts $metadata "physical_nets\t$count"
    puts $metadata "tool_version\t[version -short]"
    close $metadata
}
