"""Generate a bitstream/HDF from reviewed routed PL. Does not access hardware."""
from pathlib import Path
import argparse
import datetime
import json
import os
import shutil
import sys
import zipfile
from synth_pl_2018 import digest, run_profile, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('route', type=Path, help='Accepted route report directory')
    a = parser.parse_args()
    route = a.route.resolve()
    review = json.loads((route/'review.json').read_text())
    flow = json.loads((route/'status.json').read_text())
    if review['status'] != 'PASS' or not all(review['checks'].values()):
        raise ValueError('Requires accepted routed timing, routing, coverage and DRC')
    if flow['status'] != 'FLOW_COMPLETE':
        raise ValueError('Route flow not complete')
    if digest(route/'s_wrapper_routed.dcp') != review['checkpoint_sha256']:
        raise ValueError('Reviewed routed checkpoint changed')
    for name, expected in review['report_sha256'].items():
        if digest(route/name) != expected:
            raise ValueError('Reviewed report changed: '+name)
    root = Path(flow['synthesis_run'])
    run = root/'vivado/p.runs/impl_1'
    implementation_checkpoint = run/'s_wrapper_routed.dcp'
    original_hash = digest(implementation_checkpoint)
    if (run/'s_wrapper.bit').exists():
        raise ValueError('Bitstream already exists; refusing to overwrite')
    output = root/('bit_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir(exist_ok=False)
    state = dict(status='PREPARING', tool='Vivado 2018.3', part='xc7z015clg485-2',
                 top='s_wrapper', route_review=str(route),
                 reviewed_checkpoint_sha256=review['checkpoint_sha256'],
                 implementation_checkpoint_sha256=original_hash,
                 jobs=1, max_threads=1, hardware_programmed=False,
                 scope='Paired ORB PL; SLAM/UI run as PS Linux software; camera/HDMI hardware not integrated')
    write_json(output/'status.json',state)
    script = output/'bit.tcl'
    script.write_text('''if {[version -short] ne "2018.3"} {error "Requires Vivado 2018.3"}
set_param general.maxThreads 1
set output {%s}
open_project {%s}
if {[get_property PART [current_project]] ne "xc7z015clg485-2"} {error "Wrong part"}
if {[get_property TOP [get_filesets sources_1]] ne "s_wrapper"} {error "Wrong top"}
foreach name {synth_1 impl_1} {
    if {[get_property NEEDS_REFRESH [get_runs $name]]} {error "Stale run $name"}
}
set rundir [get_property DIRECTORY [get_runs impl_1]]
if {![file exists [file join $rundir .route_design.end.rst]] ||
    [file exists [file join $rundir .route_design.error.rst]]} {error "No completed route"}
if {[get_property STATUS [get_runs impl_1]] ne "route_design Complete!"} {error "Unexpected implementation status"}
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1
if {![file exists [file join $rundir .write_bitstream.end.rst]] ||
    [file exists [file join $rundir .write_bitstream.error.rst]]} {error "Bitstream run failed"}
foreach name {s_wrapper.bit s_wrapper.sysdef s_wrapper.hwdef} {
    if {![file exists [file join $rundir $name]]} {error "Missing export $name"}
}
open_run impl_1
report_drc -file [file join $output bit_drc.rpt]
foreach violation [get_drc_violations -quiet] {
    if {[get_property SEVERITY $violation] in {Error {Critical Warning}}} {error "DRC failure $violation"}
}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup]!=1 || [llength $hold]!=1} {error "Missing routed timing paths"}
set wns [get_property SLACK $setup]
set whs [get_property SLACK $hold]
if {$wns<0 || $whs<0} {error "Negative routed timing"}
set f [open [file join $output completion.tsv] w]
puts $f "part\t[get_property PART [current_design]]"
puts $f "top\t[get_property TOP [get_filesets sources_1]]"
puts $f "design_name\t[get_property NAME [current_design]]"
puts $f "run_status\t[get_property STATUS [get_runs impl_1]]"
puts $f "wns_ns\t$wns"
puts $f "whs_ns\t$whs"
close $f
file copy [file join $rundir s_wrapper.bit] [file join $output s_wrapper.bit]
file copy [file join $rundir s_wrapper.sysdef] [file join $output s_wrapper.hdf]
file copy [file join $rundir s_wrapper.hwdef] [file join $output s_wrapper.hwdef]
set f [open [file join $output BIT_COMPLETE.txt] w]
puts $f "Vivado 2018.3; bitstream/HDF generated; no hardware access"
close $f
close_project
exit 0
''' % (output.as_posix(),(root/'vivado/p.xpr').as_posix()),encoding='utf-8')
    state.update(status='RUNNING',tcl_sha256=digest(script))
    write_json(output/'status.json',state)
    print('Starting bitstream/HDF export, one job/thread:',output,flush=True)
    try:
        rc = run_profile(['-mode','batch','-notrace','-source',script,
                          '-log',output/'vivado.log','-journal',output/'vivado.jou'],
                         output,output/'console.log',dict(os.environ))
        state['returncode'] = rc
        if rc or not (output/'BIT_COMPLETE.txt').is_file():
            raise RuntimeError('Vivado bitstream/export failed; see console.log')
        if digest(implementation_checkpoint) != original_hash:
            raise RuntimeError('Routed checkpoint changed during bitstream stage')
        with zipfile.ZipFile(output/'s_wrapper.hdf') as z:
            if z.testzip():
                raise RuntimeError('HDF CRC failure')
            bits = [n for n in z.namelist() if n.endswith('.bit')]
            if len(bits)!=1 or z.read(bits[0])!=(output/'s_wrapper.bit').read_bytes():
                raise RuntimeError('HDF embedded bitstream differs from exported bitstream')
            state['hdf_contents'] = z.namelist()
        metrics = dict(line.split('\t',1) for line in (output/'completion.tsv').read_text().splitlines())
        for key, expected in [('wns_ns',review['timing']['wns_ns']),('whs_ns',review['timing']['whs_ns'])]:
            if abs(float(metrics[key])-expected)>0.0001:
                raise RuntimeError('Timing changed after route review: '+key)
        state.update(status='PASS',bitstream_generated=True,metrics=metrics,
                     artifacts={n:dict(bytes=(output/n).stat().st_size,sha256=digest(output/n))
                                for n in ['s_wrapper.bit','s_wrapper.hdf','s_wrapper.hwdef','bit_drc.rpt']})
        shutil.copyfile(route/'review.json',output/'source_route_review.json')
    except Exception as error:
        state.update(status='FAIL',error=str(error))
        raise
    finally:
        write_json(output/'status.json',state)
    print(state['status'],output,flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
