"""Compile unchanged vendor FP simulation models and their reported dependencies."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    vendor=Path(os.environ['FPGA_VIVADO_ROOT'])/'data/ip/xilinx';sim=Path(os.environ['FPGA_MODELSIM_BIN']);done=set();active=set();records=[]
    def command(exe,args,log):
        with (out/log).open('w') as f:r=subprocess.run([str(sim/exe),*map(str,args)],cwd=out,stdout=f,stderr=subprocess.STDOUT)
        return r.returncode,(out/log).read_text(errors='replace')
    command('vmap.exe',['-c'],'init.log')
    def build(name):
        if name in done:return
        if name in active:raise RuntimeError('Cyclic vendor dependency '+name)
        active.add(name);folder=vendor/name.rsplit('_',1)[0]
        if name=='unisims_ver':
            base=Path(os.environ['FPGA_VIVADO_ROOT'])/'data/verilog/src'
            files=[*sorted((base/'unisims').glob('*.v')),*sorted((base/'retarget').glob('*.v'))]
            command('vlib.exe',[name],name+'_vlib.log');command('vmap.exe',[name,out/name],name+'_vmap.log')
            listing=out/'unisims_ver_sources.f';listing.write_text('\n'.join('"'+f.as_posix()+'"' for f in files)+'\n')
            code,log=command('vlog.exe',['-work',name,'-f',listing],'unisims_ver_compile.log')
            if code:raise RuntimeError(log[-2000:])
            active.remove(name);done.add(name)
            records.extend(dict(library=name,source=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files)
            return
        if name=='unisim':
            base=Path(os.environ['FPGA_VIVADO_ROOT'])/'data/vhdl/src/unisims'
            files=[base/'unisim_VPKG.vhd',base/'unisim_retarget_VCOMP.vhd',*sorted((base/'primitive').glob('*.vhd')),*sorted((base/'retarget').glob('*.vhd'))]
            command('vlib.exe',[name],name+'_vlib.log');command('vmap.exe',[name,out/name],name+'_vmap.log')
            listing=out/'unisim_sources.f';listing.write_text('\n'.join('"'+f.as_posix()+'"' for f in files)+'\n')
            code,log=command('vcom.exe',['-2008','-work',name,'-f',listing],'unisim_compile.log')
            if code:raise RuntimeError(log[-2000:])
            active.remove(name);done.add(name)
            records.extend(dict(library=name,source=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files)
            return
        candidates=list((folder/'hdl').glob('*.vhd'))
        if len(candidates)!=1:raise RuntimeError('Ambiguous vendor source '+name)
        file=candidates[0];command('vlib.exe',[name],name+'_vlib.log');command('vmap.exe',[name,out/name],name+'_vmap.log')
        for attempt in range(8):
            code,log=command('vcom.exe',['-2008','-work',name,file],name+f'_compile{attempt}.log')
            if not code:break
            missing=list(dict.fromkeys(re.findall(r'Library "(\w+)" not found',log)))
            if not missing:raise RuntimeError('Vendor compilation failed: '+log[-1800:])
            for dependency in missing:build(dependency)
        else:raise RuntimeError('Vendor dependency retries exhausted')
        records.append(dict(library=name,source=str(file),sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
        active.remove(name);done.add(name)
    build('floating_point_v7_1_19')
    code,log=command('vlog.exe',['-work','floating_point_v7_1_19',vendor/'floating_point_v7_1/hdl/floating_point_v7_1_rfs.v'],'floating_verilog.log')
    if code:raise RuntimeError(log[-1600:])
    (out/'vendor_simulation.json').write_text(json.dumps(dict(status='VENDOR_MODELS_COMPILED',models=records),indent=2)+'\n')
    print('VENDOR_FLOAT_SIMLIB_PASS',len(records))
if __name__=='__main__':main()
