import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from cocotb_tools.runner import get_results,get_runner
from gpi_runtime import configure


def run(a):
    state=json.loads((a.hls/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['Cosim'] and state['Kernel']=='merge4'
    for entry in json.loads((a.hls/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert hashlib.sha256((a.hls/'inputs'/entry['Path']).read_bytes()).hexdigest().upper()==entry['SHA256']
    relative='inputs/FPGA_ORB_HLS/fastv2/next/src/front4_stream.hpp'
    bodies=[(p/relative).read_text().split('void serialize_front4_quads(',1)[1] for p in (a.hls,a.production)]
    assert bodies[0]==bodies[1],'The isolated unit differs from the frozen production serializer'
    scratch=Path(os.environ['FPGA_VIVADO_BUILD_ROOT'])/'orb60'/('m'+a.output.name[-8:]);scratch.mkdir(exist_ok=False)
    rtl=a.hls/'projects/merge4/solution1/syn/verilog';manifest=[]
    for path in rtl.iterdir():
        if path.suffix in ('.v','.sv','.dat'):
            shutil.copyfile(path,scratch/path.name);manifest.append(dict(name=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (a.output/'rtl_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    os.environ['MGLS_LICENSE_FILE']=os.environ['FPGA_MODELSIM_LICENSE']
    os.environ['PATH']=os.environ['FPGA_MODELSIM_BIN']+os.pathsep+os.environ['PATH']
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    os.environ['ORB60_MERGE4_RESULT']=str(a.output/'result.json');configure(a.output/'runtime')
    period_ps=int(state['PeriodNs']*1000);assert period_ps in (8000,10000)
    os.environ['ORB60_MERGE4_CLOCK_PS']=str(period_ps)
    runner=get_runner('questa');runner.build(hdl_toplevel='fastv2_merge4_hls',sources=sorted(scratch.glob('*.v')),build_dir=scratch,always=True)
    results=runner.test(hdl_toplevel='fastv2_merge4_hls',test_module='test_merge4_axis',build_dir=scratch)
    total,failed=get_results(results);assert total and not failed
    proof=json.loads((a.output/'result.json').read_text());assert proof['status']=='PASS' and proof['cases']==17 and proof['reset']['reset_live']
    print('MERGE4_RANDOM_AXIS_PASS masks=0..15,mixed reset_live',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('hls','production','output'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
