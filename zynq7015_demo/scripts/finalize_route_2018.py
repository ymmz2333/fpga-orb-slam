"""Write bit/HDF from an accepted optimized DCP, preserving project run artifacts."""
from pathlib import Path
import argparse
import datetime
import json
import os
import shutil
import zipfile
from synth_pl_2018 import digest,run_profile,write_json


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('route',type=Path)
    a=p.parse_args();source=a.route.resolve()
    review=json.loads((source/'review.json').read_text());old=json.loads((source/'status.json').read_text())
    if review['status']!='PASS' or not all(review['checks'].values()):raise ValueError('Requires accepted route review')
    checkpoint=source/'s_wrapper_routed.dcp'
    if digest(checkpoint)!=review['checkpoint_sha256']:raise ValueError('Checkpoint changed')
    for name,expected in review['report_sha256'].items():
        if digest(source/name)!=expected:raise ValueError('Report changed: '+name)
    root=Path(old['synthesis_run']);hwdef=root/'vivado/p.runs/impl_1/s_wrapper.hwdef'
    out=root/('final_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir(exist_ok=False)
    state=dict(status='RUNNING',tool='Vivado 2018.3',part=old['part'],top=old['top'],video2=old.get('video2',False),
        source_route=str(source),source_checkpoint_sha256=digest(checkpoint),hwdef_sha256=digest(hwdef),
        hardware_programmed=False,scope='ORB + HDMI_2 PL; PS SLAM/UI; camera hardware excluded')
    write_json(out/'status.json',state)
    script=out/'finalize.tcl'
    script.write_text('''if {[version -short] ne "2018.3"} {error "Requires 2018.3"}
set_param general.maxThreads 1
set output {%s}
open_checkpoint {%s}
if {[get_property PART [current_design]] ne "xc7z015clg485-2"} {error "Wrong part"}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[get_property SLACK $setup]<0 || [get_property SLACK $hold]<0} {error "Negative saved timing"}
report_drc -file [file join $output bit_drc.rpt]
foreach item [get_drc_violations -quiet] {
    if {[get_property SEVERITY $item] in {Error {Critical Warning}}} {error "DRC failure $item"}
}
write_bitstream [file join $output s_wrapper.bit]
write_sysdef -hwdef {%s} -bitfile [file join $output s_wrapper.bit] [file join $output s_wrapper.sysdef]
set f [open [file join $output BIT_COMPLETE.txt] w];puts $f "Accepted optimized DCP; bit/sysdef generated; no hardware programming";close $f
exit 0
'''%(out.as_posix(),checkpoint.as_posix(),hwdef.as_posix()),encoding='utf-8')
    print('Starting accepted DCP bit/HDF export:',out,flush=True)
    rc=run_profile(['-mode','batch','-notrace','-source',script,'-log',out/'vivado.log','-journal',out/'vivado.jou'],out,out/'console.log',dict(os.environ))
    if rc or not (out/'BIT_COMPLETE.txt').exists():
        state.update(status='FAIL',returncode=rc);write_json(out/'status.json',state);raise RuntimeError('Bit export failed')
    shutil.copyfile(out/'s_wrapper.sysdef',out/'s_wrapper.hdf');shutil.copyfile(hwdef,out/'s_wrapper.hwdef')
    with zipfile.ZipFile(out/'s_wrapper.hdf') as z:
        if z.testzip():raise ValueError('HDF CRC failed')
        bits=[n for n in z.namelist() if n.endswith('.bit')]
        if len(bits)!=1 or z.read(bits[0])!=(out/'s_wrapper.bit').read_bytes():raise ValueError('HDF bit differs')
        state['hdf_contents']=z.namelist()
    state.update(status='PASS',returncode=rc,bitstream_generated=True,
                 artifacts={name:dict(bytes=(out/name).stat().st_size,sha256=digest(out/name)) for name in ['s_wrapper.bit','s_wrapper.hdf','s_wrapper.hwdef','bit_drc.rpt']})
    write_json(out/'status.json',state);shutil.copyfile(source/'review.json',out/'source_route_review.json')
    print('PASS',out,flush=True)


if __name__=='__main__':main()
