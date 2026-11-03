"""Strict K26 64-bit variant of the retained randomized AXI protocol gate."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[3]


def run(a):
    sys.path[:0]=[str(ROOT/'orb60/tests'),str(ROOT/'tb')]
    from cocotb_tools.runner import get_runner,get_results
    from gpi_runtime import configure as configure_runtime
    from orb60.kv260.register_map import parse_header
    job=a.job.resolve();out=a.output.resolve();vectors=a.vectors.resolve();kernel=a.kernel
    if not (job/'unit_pass.stamp').is_file():raise ValueError('Require completed K26 CSim/synthesis/cosimulation/IP export')
    recipe=json.loads((job/'recipe.json').read_text())
    if recipe['part']!='xck26-sfvc784-2LV-c' or recipe['m_axi_address_bits']!=64:raise ValueError('Wrong target/ABI')
    info=json.loads((vectors/'vectors.json').read_text())
    for name,digest in info['sha256'].items():
        if hashlib.sha256((vectors/name).read_bytes()).hexdigest()!=digest:raise ValueError('Golden vector changed: '+name)
    out.mkdir(parents=True,exist_ok=False)
    top=f'fastv2_{kernel}_hls'
    header=job/f'project/solution1/impl/misc/drivers/{top}_v1_0/src/x{top}_hw.h'
    abi=parse_header(header)
    offsets={name.removesuffix('_DATA'):value for name,value in abi['offsets'].items()}
    pointers=('RAW','BLURRED','POINTS','FEATURES','STATS') if kernel=='descriptor' else ('IMAGE_R','BLURRED','RESIZED','SELECTED','RESULT','STATS')
    if any(abi['widths'][n+'_DATA']!=64 for n in pointers):raise ValueError('Pointer is not 64-bit')
    text=(ROOT/'orb60/tests/test_datapath_axi.py').read_text()
    replacements={
        'assert len(getattr(dut,prefix+\'_ARADDR\'))==32':"assert len(getattr(dut,prefix+'_ARADDR'))==64",
        'for key,value in pointers.items():await control.write(offsets[key],value)':
            'for key,value in pointers.items():\n        await control.write(offsets[key],value&0xffffffff)\n        await control.write(offsets[key]+4,value>>32)',
        'BASE=0x100000':'BASE=0x100100000',
    }
    for key in ('RAW','BLUR','NEXT','POINTS','RESULT','STATS','DESCRIPTOR_POINTS','FEATURES'):
        import re
        match=re.search(r'^'+key+r'=(0x[0-9a-fA-F]+)$',text,re.M)
        if not match:raise ValueError('Unknown retained test address: '+key)
        replacements[match[0]]=key+'='+hex(int(match[1],16)+0x100000000)
    for old,new in replacements.items():
        if text.count(old)!=1:raise ValueError('Retained protocol test anchor changed: '+old)
        text=text.replace(old,new)
    (out/'kv260_datapath_axi.py').write_text(text)
    config=dict(kernel=kernel,vectors=str(vectors),offsets=offsets,cases=[int(x) for x in a.cases.split(',')],
                reset_case=a.reset_case,result=str(out/'result.json'),clock_period_ps=round(recipe['period_ns']*1000),layer_ppc=recipe['defines']['ORB60_LAYER_PPC'])
    (out/'config.json').write_text(json.dumps(config,indent=2))
    scratch=Path(os.environ['FPGA_VIVADO_BUILD_ROOT'])/'kv260'/out.name
    scratch.mkdir(parents=True,exist_ok=False)
    rtl_manifest={}
    for path in (job/'project/solution1/syn/verilog').iterdir():
        if path.suffix in ('.v','.sv','.dat'):
            shutil.copy2(path,scratch/path.name);rtl_manifest[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'rtl_manifest.json').write_text(json.dumps(rtl_manifest,indent=2))
    sys.path.insert(0,str(out))
    os.environ['PYTHONPATH']=os.pathsep.join([str(out),str(ROOT/'orb60/tests'),str(ROOT/'tb'),os.environ.get('PYTHONPATH','')])
    os.environ['ORB60_DATAPATH_CONFIG']=str(out/'config.json')
    os.environ['MGLS_LICENSE_FILE']=os.environ['FPGA_MODELSIM_LICENSE']
    os.environ['PATH']=os.environ['FPGA_MODELSIM_BIN']+os.pathsep+os.environ['PATH']
    configure_runtime(out/'runtime')
    status={'state':'RUNNING','address_bits':64,'ddr_base':'0x100100000','scope':'Random AXI stalls/reset/4KB boundaries and exact golden bytes; not DDR PHY or integrated routing',
            'started_utc':datetime.now(timezone.utc).isoformat()}
    try:
        (out/'status.json').write_text(json.dumps(status,indent=2))
        runner=get_runner('questa');runner.build(hdl_toplevel=top,sources=sorted(scratch.glob('*.v'))+sorted(scratch.glob('*.sv')),build_dir=scratch,always=True)
        result=runner.test(hdl_toplevel=top,test_module='kv260_datapath_axi',build_dir=scratch)
        total,failed=get_results(result)
        if not total or failed:raise RuntimeError(f'RTL protocol test failed: {failed}/{total}; inspect simulator transcript')
        proof=json.loads((out/'result.json').read_text())
        if not total or failed or proof.get('status')!='PASS' or not proof['reset_interruption'] or not proof['direct_completion_barrier'] or proof['transactions']!=len(config['cases']):
            raise RuntimeError('64-bit AXI acceptance failed')
        runtime=json.loads((out/'runtime/python_runtime.json').read_text())
        if Path(runtime['loaded_dll'])!=Path(runtime['expected_dll']):raise RuntimeError('Wrong embedded Python')
        status['state']='SUCCEEDED'
    except BaseException as e:status.update(state='FAILED',error=str(e));raise
    finally:
        status['finished_utc']=datetime.now(timezone.utc).isoformat();(out/'status.json').write_text(json.dumps(status,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--vectors',type=Path,required=True)
    p.add_argument('--kernel',choices=['layer2','descriptor'],required=True);p.add_argument('--cases',required=True);p.add_argument('--reset-case',type=int,required=True);run(p.parse_args())
