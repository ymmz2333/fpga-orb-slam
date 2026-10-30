# Pure parser regression under XSCT; never invokes JTAG commands.
source [file join [file dirname [info script]] board_result.tcl]
# @brief Require an exception for a malformed or falsely verified terminal result.
# @param words Candidate mailbox; schema/mode are expected firmware settings.
proc reject {words schema mode {schedule Serial}} {
    if {![catch {next_validate_result $words 100 $schema $mode $schedule}]} { error "Invalid success accepted" }
}
set words [lrepeat 128 0]
foreach {index value} {1 100 2 0x4E585452 3 4 4 2 6 100 10 100000000 26 1 27 100} { lset words $index $value }
if {[next_validate_result $words 100 4 Verified] ne "PASS"} { error "Valid exact PASS rejected" }
foreach {index value} {1 99 2 0 3 3 4 4 5 1 6 99 10 50000000 26 2 27 0} {
    set bad $words; lset bad $index $value; reject $bad 4 Verified
}
set production $words
foreach {index value} {4 4 26 2 27 0} { lset production $index $value }
if {[next_validate_result $production 100 4 Production] ne "COMPLETE_UNVERIFIED"} { error "Production completion rejected" }
foreach {index value} {4 2 16 1 24 1 25 1 27 100 28 1} {
    set bad $production; lset bad $index $value; reject $bad 4 Production
}
set legacy $words; lset legacy 3 3
if {[next_validate_result $legacy 100 3 Legacy] ne "PASS"} { error "Old exact PASS rejected" }
reject $legacy 3 Verified
set serial $words; lset serial 3 5
if {[next_validate_result $serial 100 5 Verified Serial] ne "PASS"} { error "Schema-5 serial rejected" }
set pipeline $serial
foreach {index value} {112 1 113 700 114 1} { lset pipeline $index $value }
if {[next_validate_result $pipeline 100 5 Verified Pipeline] ne "PASS"} { error "Pipeline PASS rejected" }
foreach {index value} {112 0 113 699 114 0 115 1 116 4} {
    set bad $pipeline; lset bad $index $value; reject $bad 5 Verified Pipeline
}
reject $pipeline 5 Verified Serial
reject $serial 5 Verified Pipeline
reject $pipeline 5 Legacy Pipeline
reject $words 4 Verified Pipeline
set piprod $pipeline
foreach {index value} {4 4 26 2 27 0} { lset piprod $index $value }
if {[next_validate_result $piprod 100 5 Production Pipeline] ne "COMPLETE_UNVERIFIED"} { error "Pipeline production rejected" }
set failure $pipeline; lset failure 4 3; lset failure 5 8; lset failure 116 4
if {[next_validate_result $failure 100 5 Verified Pipeline] ne "FAIL"} { error "Timeout FAIL rejected" }
puts "NEXT_BOARD_RESULT_PARSER_PASS faults=25 no_JTAG=1"
