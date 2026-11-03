"""Isolated native A53/O3 Optimizer TU; all retained binaries stay untouched."""
import argparse
import json
from pathlib import Path
import platform
import shlex
import subprocess
import time
from .build_network_adapter import digest


def run(root,adapter,output):
    root,adapter,output=map(lambda p:Path(p).resolve(),(root,adapter,output))
    if platform.machine()!='aarch64':raise ValueError('Actual native KV260 compiler required')
    base=json.loads((adapter/'BUILD.json').read_text())
    if base['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Verified native network adapter required')
    for path,expected in base['products_sha256'].items():
        if digest(path)!=expected:raise ValueError('Adapter product changed')
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))
    if available<1536*1024:raise ValueError('At least1536MiB free memory required for single-compiler experiment')
    output.mkdir(parents=True,exist_ok=False)
    for name in ('source','lib','bin'):(output/name).mkdir()
    source=root/'slam/src/Optimizer.cc';private=output/'source/Optimizer.cc';private.write_bytes(source.read_bytes())
    compile_command=base['commands'][0]
    if compile_command.count('-O2')!=1 or any(x in compile_command for x in ('-ffast-math','-Ofast')):
        raise ValueError('Unreviewed original compiler options')
    common=compile_command[:compile_command.index('-c')]
    common[common.index('-O2')]='-O3';common+=['-mcpu=cortex-a53']
    liblink=list(base['commands'][1]);original='CMakeFiles/ORB_SLAM3.dir/src/Optimizer.cc.o'
    if liblink.count(original)!=1:raise ValueError('Optimizer object is ambiguous')
    liblink[liblink.index(original)]=str(output/'Optimizer.o')
    liblink[liblink.index('-o')+1]=str(output/'lib/libORB_SLAM3.so')
    exelink=list(base['commands'][3]);oldlib=str(adapter/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Adapter link mismatch')
    exelink[exelink.index(oldlib)]=str(output/'lib/libORB_SLAM3.so')
    exelink[exelink.index('-o')+1]=str(output/'bin/mono_kv260_network')
    for i,value in enumerate(exelink):
        if value.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(output/'lib')+':'+value.removeprefix('-Wl,-rpath,')
    commands=[[*common,'-c',str(private),'-o',str(output/'Optimizer.o')],liblink,exelink]
    protected=[*list((root/'build').rglob('*.o')),root/'build/lib/libORB_SLAM3.so',
               adapter/'lib/libORB_SLAM3.so',adapter/'bin/mono_kv260_network']
    before={str(p):digest(p) for p in protected}
    state={'status':'RUNNING','scope':'Compiler-only PS optimization candidate; functional and actual full-system gates remain separate',
           'source_sha256':digest(source),'adapter':str(adapter),'commands':commands,'started_monotonic_ns':time.monotonic_ns(),
           'source_algorithm_modified':False,'fast_math':False,'available_kib':available}
    save=lambda:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                log.write('COMMAND '+shlex.join(command)+'\n');log.flush()
                subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        if digest(source)!=state['source_sha256'] or digest(private)!=state['source_sha256']:
            raise ValueError('Authored optimizer source changed during compiler experiment')
        if any(digest(p)!=old for p,old in before.items()):raise ValueError('Retained products were modified')
        binary=output/'bin/mono_kv260_network';library=output/'lib/libORB_SLAM3.so'
        abi=subprocess.check_output(['file',str(binary),str(library)],text=True)
        deps=subprocess.check_output(['ldd',str(binary)],text=True)
        if abi.count('ARM aarch64')!=2 or 'not found' in deps or str(library) not in deps:
            raise ValueError('Native ELF/link dependency validation failed')
        state.update(status='NATIVE_OPTIMIZER_CANDIDATE_BUILD_PASS',architecture=abi,dependencies=deps,
                     products_sha256={str(p):digest(p) for p in (binary,library)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:state['finished_monotonic_ns']=time.monotonic_ns();save()
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
