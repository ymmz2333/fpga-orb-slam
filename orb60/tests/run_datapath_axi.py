"""Randomized AXI unit gate for frozen layer2/descriptor RTL, shared DDR space."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from cocotb_tools.runner import get_results,get_runner
from gpi_runtime import configure as configure_runtime
from run_axi import control_offsets,top_name


def run(args):
    job=args.hls_job.resolve();vectors=args.vectors.resolve();output=args.output.resolve()
    state=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['Cosim'] and state['Kernel']==args.kernel
    for entry in json.loads((job/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert hashlib.sha256((job/'inputs'/entry['Path']).read_bytes()).hexdigest().upper()==entry['SHA256']
    vector_info=json.loads((vectors/'vectors.json').read_text())
    for name,digest in vector_info['sha256'].items():
        assert hashlib.sha256((vectors/name).read_bytes()).hexdigest()==digest
    output.mkdir(parents=True,exist_ok=False)
    status_path=output/'status.json'
    record=dict(state='RUNNING',kernel=args.kernel,hls_job=str(job),started_utc=datetime.now(timezone.utc).isoformat(),
                scope='Isolated IP random AXI/reset/direct done barrier; common DDR address space, no DDR PHY or two-core contention')
    status_path.write_text(json.dumps(record,indent=2))
    try:
        top=top_name(job,args.kernel)
        scratch=Path(os.environ['FPGA_VIVADO_BUILD_ROOT'])/'orb60'/('a'+output.parent.name[-8:])/args.kernel
        scratch.mkdir(parents=True,exist_ok=False)
        manifest=[]
        for source in (job/f'projects/{args.kernel}/solution1/syn/verilog').iterdir():
            if source.suffix in ('.v','.sv','.dat'):
                shutil.copyfile(source,scratch/source.name)
                manifest.append(dict(name=source.name,sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        (output/'rtl_manifest.json').write_text(json.dumps(manifest,indent=2))
        cases=[int(i) for i in args.cases.split(',')]
        result=output/'result.json'
        config=dict(kernel=args.kernel,vectors=str(vectors),offsets=control_offsets(job,args.kernel,top),
                    cases=cases,result=str(result),reset_case=args.reset_case)
        config['clock_period_ps']=round(state['PeriodNs']*1000)
        assert 5000<=config['clock_period_ps']<=10000 and abs(config['clock_period_ps']-state['PeriodNs']*1000)<=0.5
        if args.kernel=='layer2':config['layer_ppc']=state.get('LayerPpc',2)
        config_path=output/'config.json';config_path.write_text(json.dumps(config,indent=2))
        modelsim=Path(os.environ['FPGA_MODELSIM_BIN'])
        os.environ['MGLS_LICENSE_FILE']=os.environ['FPGA_MODELSIM_LICENSE']
        os.environ['PATH']=str(modelsim)+os.pathsep+os.environ['PATH']
        here=Path(__file__).resolve().parent
        project=Path(os.environ['FPGA_PROJECT_ROOT'])
        sys.path[:0]=[str(here),str(here.parent),str(project/'tb')]
        os.environ['ORB60_DATAPATH_CONFIG']=str(config_path)
        configure_runtime(output/'runtime')
        print(f'ORB60_DATAPATH_AXI_BEGIN kernel={args.kernel} cases={cases}',flush=True)
        runner=get_runner('questa')
        runner.build(hdl_toplevel=top,sources=sorted(scratch.glob('*.v'))+sorted(scratch.glob('*.sv')),
                     build_dir=scratch,always=True)
        test_result=runner.test(hdl_toplevel=top,test_module='test_datapath_axi',build_dir=scratch)
        total,failed=get_results(test_result)
        proof=json.loads(result.read_text()) if result.exists() else {}
        assert total>0 and failed==0 and proof.get('status')=='PASS'
        assert proof['transactions']==len(cases) and proof['reset_interruption'] and proof['direct_completion_barrier']
        runtime=json.loads((output/'runtime/python_runtime.json').read_text())
        assert Path(runtime['loaded_dll'])==Path(runtime['expected_dll'])
        record.update(state='SUCCEEDED',result=str(result),runtime=runtime)
        print(f'ORB60_DATAPATH_AXI_PASS kernel={args.kernel} cases={len(cases)}',flush=True)
    except BaseException as error:
        record.update(state='FAILED',error=str(error));raise
    finally:
        record['finished_utc']=datetime.now(timezone.utc).isoformat()
        status_path.write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--hls-job',type=Path,required=True);p.add_argument('--vectors',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--kernel',choices=('layer2','descriptor'),required=True)
    p.add_argument('--cases',required=True);p.add_argument('--reset-case',type=int,required=True)
    run(p.parse_args())
