"""Optimize a preserved routed checkpoint; report independently, no bitstream."""
from pathlib import Path
import argparse
import datetime
import json
import os
from synth_pl_2018 import digest,run_profile,write_json


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('route',type=Path)
    a=p.parse_args();source=a.route.resolve()
    old=json.loads((source/'status.json').read_text());review=json.loads((source/'review.json').read_text())
    checkpoint=source/'s_wrapper_routed.dcp'
    if old['status']!='FLOW_COMPLETE' or digest(checkpoint)!=review['checkpoint_sha256']:
        raise ValueError('Requires completed, hash-reviewed route')
    out=Path(old['synthesis_run'])/('opt_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(exist_ok=False)
    state=dict(status='RUNNING',tool='Vivado 2018.3',part=old['part'],top=old['top'],
        strategy='post-route critical_pin_opt + routing_opt + Explore',video2=old.get('video2',False),
        synthesis_run=old['synthesis_run'],source_route=str(source),source_checkpoint_sha256=digest(checkpoint),
        bitstream_generated=False,hardware_programmed=False,jobs=1,max_threads=1)
    write_json(out/'status.json',state)
    script=out/'optimize.tcl'
    script.write_text('''if {[version -short] ne "2018.3"} {error "Requires 2018.3"}
set_param general.maxThreads 1
set output {%s}
open_checkpoint {%s}
if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {error "Wrong part"}
phys_opt_design -critical_pin_opt
phys_opt_design -routing_opt
route_design -directive Explore
report_timing_summary -check_timing_verbose -report_unconstrained -max_paths 10 -nworst 1 -file [file join $output post_route_timing.rpt]
report_utilization -file [file join $output post_route_utilization.rpt]
report_route_status -file [file join $output post_route_route_status.rpt]
report_clocks -file [file join $output post_route_clocks.rpt]
check_timing -verbose -file [file join $output post_route_check_timing.rpt]
report_drc -file [file join $output post_route_drc.rpt]
report_methodology -file [file join $output post_route_methodology.rpt]
report_bus_skew -file [file join $output post_route_bus_skew.rpt]
report_cdc -details -file [file join $output post_route_cdc.rpt]
write_checkpoint [file join $output s_wrapper_routed.dcp]
set f [open [file join $output ROUTE_COMPLETE.txt] w];puts $f "post-route optimization complete; acceptance requires report review";close $f
exit 0
'''%(out.as_posix(),checkpoint.as_posix()),encoding='utf-8')
    print('Starting post-route optimization:',out,flush=True)
    rc=run_profile(['-mode','batch','-notrace','-source',script,'-log',out/'vivado.log','-journal',out/'vivado.jou'],out,out/'console.log',dict(os.environ))
    state.update(status='FLOW_COMPLETE' if rc==0 and (out/'ROUTE_COMPLETE.txt').exists() else 'FAIL',returncode=rc)
    write_json(out/'status.json',state);print(state['status'],out,flush=True)
    return 0 if state['status']=='FLOW_COMPLETE' else 1


if __name__=='__main__':raise SystemExit(main())
