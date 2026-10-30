"""Run place and route after accepted synthesis; no bitstream or hardware I/O."""
from pathlib import Path
import argparse
import datetime
import json
import os
import sys
from synth_pl_2018 import digest, run_profile, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='Completed synthesis run directory')
    parser.add_argument('--allow-serdes-hold-fix',action='store_true',
                        help='Allow only OSERDESE2 reset hold paths for the router to repair; final hold acceptance is unchanged')
    parser.add_argument('--incremental',type=Path,help='Read-only reference DCP for placement/routing reuse')
    a = parser.parse_args()
    root = a.run.resolve()
    synthesis = json.loads((root / 'status.json').read_text())
    review = json.loads((root / 'review.json').read_text())
    hold_fix=a.allow_serdes_hold_fix and synthesis.get('video2') and review['wns_ns']>=0 and review['setup_failing_endpoints']==0 and review['wpws_ns']>=0
    if synthesis['status'] != 'PASS' or (review['timing_status'] != 'PASS' and not hold_fix):
        raise ValueError('Requires completed synthesis and reviewed nonnegative synthesis timing')
    if synthesis.get('video2') and json.loads((root/'contract_check.json').read_text())['status']!='PASS':
        raise ValueError('Video configuration contract must pass')
    checkpoint = root / 'vivado/s_wrapper_synth.dcp'
    if digest(checkpoint) != review['checkpoint_sha256']:
        raise ValueError('Synthesis checkpoint changed after review')
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    output = root / ('route_' + stamp)
    output.mkdir(exist_ok=False)
    state = dict(status='PREPARING', scope='implementation through route_design only',
                 tool='Vivado 2018.3', part='xc7z015clg485-2', top='s_wrapper',
                 strategy='Performance_Explore', jobs=1, max_threads=1,
                 source_checkpoint=str(checkpoint), source_checkpoint_sha256=digest(checkpoint),
                 synthesis_run=str(root), bitstream_generated=False, hardware_programmed=False)
    state.update(video2=synthesis.get('video2',False),serdes_reset_hold_fix=bool(hold_fix))
    incremental=''
    if a.incremental:
        reference=a.incremental.resolve()
        state.update(incremental_reference=str(reference),incremental_reference_sha256=digest(reference))
        incremental='set_property INCREMENTAL_CHECKPOINT {'+reference.as_posix()+'} [get_runs impl_1]'
    hold_guard=''
    if hold_fix:
        hold_guard='''open_run synth_1
report_timing -delay_type min -slack_lesser_than 0 -max_paths 100 -file [file join $output serdes_reset_hold_before_route.rpt]
foreach path [get_timing_paths -delay_type min -slack_lesser_than 0 -max_paths 100] {
    set pin [get_property ENDPOINT_PIN $path]
    if {![string match "*/phy/inst/*/RST" $pin]} {error "Non-SERDES hold path must be fixed before routing: $pin"}
}
close_design
'''
    write_json(output/'status.json',state)
    script = output/'route.tcl'
    script.write_text('''if {[version -short] ne "2018.3"} {error "Requires Vivado 2018.3"}
set_param general.maxThreads 1
set output {%s}
open_project {%s}
if {[get_property PART [current_project]] ne "xc7z015clg485-2"} {error "Wrong project part"}
if {[get_property TOP [get_filesets sources_1]] ne "s_wrapper"} {error "Wrong project top"}
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {error "Synthesis not complete"}
if {[get_property NEEDS_REFRESH [get_runs synth_1]]} {error "Synthesis is stale"}
if {[get_property STATUS [get_runs impl_1]] ne "Not started"} {error "Refusing to overwrite existing implementation"}
%s
set_property strategy Performance_Explore [get_runs impl_1]
%s
launch_runs impl_1 -to_step route_design -jobs 1
wait_on_run impl_1
set rundir [get_property DIRECTORY [get_runs impl_1]]
if {![file exists [file join $rundir .route_design.end.rst]] ||
    [file exists [file join $rundir .route_design.error.rst]] ||
    ![file exists [file join $rundir s_wrapper_routed.dcp]]} {
    error "Implementation did not complete route_design: [get_property STATUS [get_runs impl_1]]"
}
open_run impl_1
report_utilization -file [file join $output post_route_utilization.rpt]
report_utilization -hierarchical -file [file join $output post_route_hierarchy.rpt]
report_timing_summary -check_timing_verbose -report_unconstrained -max_paths 10 -nworst 1 -file [file join $output post_route_timing.rpt]
report_clocks -file [file join $output post_route_clocks.rpt]
check_timing -verbose -file [file join $output post_route_check_timing.rpt]
report_route_status -file [file join $output post_route_route_status.rpt]
report_drc -file [file join $output post_route_drc.rpt]
report_methodology -file [file join $output post_route_methodology.rpt]
report_bus_skew -file [file join $output post_route_bus_skew.rpt]
report_cdc -file [file join $output post_route_cdc.rpt]
report_timing -delay_type max -max_paths 10 -nworst 1 -file [file join $output post_route_setup_paths.rpt]
report_timing -delay_type min -max_paths 10 -nworst 1 -file [file join $output post_route_hold_paths.rpt]
write_checkpoint [file join $output s_wrapper_routed.dcp]
set summary [open [file join $output completion.tsv] w]
puts $summary "part\t[get_property PART [current_design]]"
puts $summary "top\t[get_property NAME [current_design]]"
puts $summary "run_status\t[get_property STATUS [get_runs impl_1]]"
puts $summary "strategy\t[get_property STRATEGY [get_runs impl_1]]"
puts $summary "wns_ns\t[get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]"
puts $summary "whs_ns\t[get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]"
close $summary
set receipt [open [file join $output ROUTE_COMPLETE.txt] w]
puts $receipt "Vivado 2018.3; route_design complete; timing/DRC acceptance requires report review; no bitstream"
close $receipt
close_project
exit 0
''' % (output.as_posix(),(root/'vivado/p.xpr').as_posix(),hold_guard,incremental), encoding='utf-8')
    state.update(status='RUNNING', tcl_sha256=digest(script))
    write_json(output/'status.json',state)
    print('Starting place/route, one job/thread:',output,flush=True)
    rc = run_profile(['-mode','batch','-notrace','-source',script,
                      '-log',output/'vivado.log','-journal',output/'vivado.jou'],
                     output,output/'console.log',dict(os.environ))
    state.update(status='FLOW_COMPLETE' if rc == 0 and (output/'ROUTE_COMPLETE.txt').is_file() else 'FAIL',returncode=rc)
    write_json(output/'status.json',state)
    print(state['status'],output,flush=True)
    return 0 if state['status']=='FLOW_COMPLETE' else 1


if __name__=='__main__':
    sys.exit(main())
