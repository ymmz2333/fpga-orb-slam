import argparse,json,os,sys,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def main():
    p=argparse.ArgumentParser();p.add_argument('hls',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    job=a.hls.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if not (job/'unit_pass.stamp').exists():raise ValueError('HLS gates required')
    vectors=json.loads((job/'vectors/vectors.json').read_text())
    for name,expected in vectors['sha256'].items():
        if hashlib.sha256((job/'vectors'/name).read_bytes()).hexdigest()!=expected:raise ValueError('Golden input changed: '+name)
    snapshot=out/'test_source';snapshot.mkdir()
    for name in ['run_axi.py','test_axi.py','reference.py']:
        shutil.copy2(Path(__file__).with_name(name),snapshot/name)
    sys.path[:0]=[str(ROOT/'orb60/tests'),str(ROOT/'tb'),str(ROOT)]
    from gpi_runtime import configure
    from orb60.kv260.register_map import parse_header
    from cocotb_tools.runner import get_runner,get_results
    abi=parse_header(job/'project/solution1/impl/misc/drivers/point_project_hls_v1_0/src/xpoint_project_hls_hw.h')
    for name in ['SAMPLES','CONFIG_R','POINTS','STATS']:assert abi['widths'][name+'_DATA']==64
    (out/'abi.json').write_text(json.dumps(abi,indent=2)+'\n')
    config=dict(vectors=str(job/'vectors'),offsets=abi['offsets'],output=str(out/'result.json'))
    (out/'config.json').write_text(json.dumps(config,indent=2))
    scratch=Path(os.environ['FPGA_VIVADO_BUILD_ROOT'])/out.name;scratch.mkdir(parents=True,exist_ok=False)
    for f in (job/'project/solution1/syn/verilog').iterdir():
        if f.suffix in ('.v','.sv','.dat'):shutil.copy2(f,scratch/f.name)
    for f in (job/'project/solution1/sim/verilog/ip/xil_defaultlib').glob('*.v'):shutil.copy2(f,scratch/f.name)
    os.environ['POINT_AXI_CONFIG']=str(out/'config.json')
    os.environ['PYTHONPATH']=os.pathsep.join([str(ROOT),str(ROOT/'orb60/tests'),str(ROOT/'tb')])
    os.environ['MGLS_LICENSE_FILE']=os.environ['FPGA_MODELSIM_LICENSE'];os.environ['PATH']=os.environ['FPGA_MODELSIM_BIN']+os.pathsep+os.environ['PATH']
    configure(out/'runtime');runner=get_runner('questa')
    os.environ['MODELSIM']=os.environ['POINT_SIMLIB']+'/modelsim.ini'
    runner.build(hdl_toplevel='point_project_hls',sources=sorted(scratch.glob('*.v'))+sorted(scratch.glob('*.sv')),build_dir=scratch,always=True)
    libs=json.loads((Path(os.environ['POINT_SIMLIB'])/'vendor_simulation.json').read_text())
    if libs.get('status')!='VENDOR_MODELS_COMPILED':raise ValueError('Official simulation library build did not pass')
    shutil.copy2(Path(os.environ['POINT_SIMLIB'])/'vendor_simulation.json',out/'vendor_simulation.json')
    library_args=[]
    for name in sorted(set(x['library'] for x in libs['models'])):library_args+=['-L',name]
    result=runner.test(hdl_toplevel='point_project_hls',test_module='orb60.kv260.point_pl.test_axi',build_dir=scratch,test_args=library_args)
    total,failed=get_results(result)
    if not total or failed:raise RuntimeError('Random AXI test failed')
    proof=json.loads((out/'result.json').read_text())
    if proof['status']!='PASS' or proof['transactions']!=9 or not proof['direct_completion_barrier']:raise RuntimeError('Incomplete protocol proof')
    manifest={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in scratch.iterdir() if f.suffix in ('.v','.sv','.dat')}
    (out/'rtl_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('POINT_PROJECT_RANDOM_AXI_PASS')
if __name__=='__main__':main()
