"""Bounded self-checking HDMI/video RTL simulation using Vivado 2018.3 XSim."""
from pathlib import Path
import argparse
import datetime
import os
import re
import sys
from synth_pl_2018 import digest, run_profile, write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top',choices=['tb_tmds','tb_video','tb_video_full','tb_serializer'],default='tb_tmds')
    a=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    # Keep the 2018.3 Windows simulator project path below 80 characters.
    out=root.parent/'.work/vs18'/(datetime.datetime.now().strftime('%m%d_%H%M%S_%f')+'_'+a.top.removeprefix('tb_'))
    out.mkdir(parents=True,exist_ok=False)
    source=list(sorted((root/'rtl/video').glob('*.v')))+[root/'tests/rtl'/('tb_video.sv' if a.top=='tb_video_full' else a.top+'.sv')]
    state=dict(status='RUNNING',top=a.top,tool='Vivado 2018.3 XSim',
               inputs={str(p.relative_to(root)):digest(p) for p in source})
    write_json(out/'checks.json',state)
    script=out/'simulate.tcl'
    script.write_text('''if {[version -short] ne "2018.3"} {error "Requires 2018.3"}
set_param general.maxThreads 1
create_project sim {%s} -part xc7z015clg485-2
set_property XPM_LIBRARIES {XPM_FIFO XPM_CDC} [current_project]
add_files [list {%s}]
set_property top %s [get_filesets sim_1]
set_property target_simulator XSim [current_project]
set_property xsim.simulate.runtime all [get_filesets sim_1]
set_property xsim.elaborate.mt_level off [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation -simset sim_1 -mode behavioral
close_sim
close_project
exit 0
'''%( (out/'project').as_posix(),'} {'.join(p.as_posix() for p in source),a.top),encoding='utf-8')
    rc=run_profile(['-mode','batch','-notrace','-source',script,'-log',out/'vivado.log','-journal',out/'vivado.jou'],
                   out,out/'console.log',dict(os.environ))
    logs=list(out.rglob('simulate.log'))+list(out.rglob('xsim.log'))
    transcripts=[p.read_text(errors='replace') for p in logs]
    passed=any('TEST_PASS' in s and not re.search(r'(?:Fatal:|\bFATAL\b|\bERROR:)',s) for s in transcripts)
    state.update(status='PASS' if rc==0 and passed else 'FAIL',returncode=rc,
                 logs=[str(p) for p in logs],hardware_execution='NOT_RUN')
    write_json(out/'checks.json',state)
    print(state['status'],out,flush=True)
    for s in transcripts:
        print(s[-2500:],flush=True)
    return 0 if state['status']=='PASS' else 1


if __name__=='__main__':
    sys.exit(main())
