"""Bounded native A53/O3 build of the unchanged PoseOptimization function only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import signal
import subprocess
import time
from .build_network_adapter import digest


def extract(source):
    signature='int Optimizer::PoseOptimization(Frame *pFrame)'
    following='void Optimizer::LocalBundleAdjustment(KeyFrame *pKF'
    if source.count(signature)!=1 or source.count(following)!=1:raise ValueError('Unreviewed pose source boundary')
    start=source.index(signature);end=source.index(following,start)
    body=source[start:end].rstrip()
    if not body.endswith('}') or body.count('Optimizer::')!=1:raise ValueError('Ambiguous pose function body')
    prefix=source[:source.index('namespace ORB_SLAM3')]
    if prefix.count('#include "Optimizer.h"')!=1:raise ValueError('Optimizer include prefix mismatch')
    return prefix+'namespace ORB_SLAM3 {\n'+body+'\n}\n',body


def available():
    return int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))


def symbols(path,dynamic=False):
    command=['nm','-D' if dynamic else '-g','--defined-only',str(path)]
    return [line.split() for line in subprocess.check_output(command,text=True).splitlines() if 'PoseOptimization' in line]


def run(root,adapter,output):
    root,adapter,output=map(lambda p:Path(p).resolve(),(root,adapter,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and at least1536MiB available memory required')
    base=json.loads((adapter/'BUILD.json').read_text())
    if base['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Verified adapter required')
    for p,h in base['products_sha256'].items():
        if digest(p)!=h:raise ValueError('Adapter product changed')
    source=root/'slam/src/Optimizer.cc';text=source.read_bytes().decode('utf-8');private,body=extract(text)
    original=root/'build/CMakeFiles/ORB_SLAM3.dir/src/Optimizer.cc.o';sym=symbols(original)
    if len(sym)!=1 or sym[0][1]!='T':raise ValueError('Original strong pose symbol mismatch')
    name=sym[0][2]
    if subprocess.check_output(['c++filt',name],text=True).strip()!='ORB_SLAM3::Optimizer::PoseOptimization(ORB_SLAM3::Frame*)':
        raise ValueError('Pose ABI mismatch')
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','lib','bin'):(output/folder).mkdir()
    (output/'source/PoseOptimization.cc').write_bytes(private.encode())
    compile_base=base['commands'][0];common=compile_base[:compile_base.index('-c')]
    if common.count('-O2')!=1:raise ValueError('Original compiler flags mismatch')
    common[common.index('-O2')]='-O3';common+=['-mcpu=cortex-a53']
    weak=output/'RetainedOptimizer.o';obj=output/'PoseOptimization.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink=list(base['commands'][1]);old='CMakeFiles/ORB_SLAM3.dir/src/Optimizer.cc.o'
    if liblink.count(old)!=1:raise ValueError('Original optimizer link mismatch')
    liblink[liblink.index(old)]=str(weak)
    # The new strong pose definition and its optimized inline templates precede
    # retained weak template definitions. All other strong functions are retained.
    liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(obj))
    liblink[liblink.index('-o')+1]=str(lib)
    exelink=list(base['commands'][3]);oldlib=str(adapter/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Adapter executable link mismatch')
    exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,value in enumerate(exelink):
        if value.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+value.removeprefix('-Wl,-rpath,')
    commands=[['objcopy','--weaken-symbol='+name,str(original),str(weak)],
              [*common,'-c',str(output/'source/PoseOptimization.cc'),'-o',str(obj)],liblink,exelink]
    protected=[*list((root/'build').rglob('*.o')),root/'build/lib/libORB_SLAM3.so',adapter/'lib/libORB_SLAM3.so',adapter/'bin/mono_kv260_network']
    before={str(p):digest(p) for p in protected}
    state=dict(status='RUNNING',scope='Private PS pose compiler candidate, not a functional/performance pass',
               commands=commands,source_sha256=digest(source),function_sha256=hashlib.sha256(body.encode()).hexdigest(),
               function_body_unchanged=True,fast_math=False,pose_symbol=name,started_monotonic_ns=time.monotonic_ns())
    def save():(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                log.write('COMMAND '+shlex.join(command)+'\n');log.flush()
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                while child.poll() is None:
                    if available()<262144:
                        os.killpg(child.pid,signal.SIGTERM);child.wait()
                        raise MemoryError('Private compiler stopped below256MiB available memory')
                    time.sleep(.5)
                if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        if symbols(weak)[0][1]!='W' or symbols(obj)[0][1]!='T' or symbols(lib,True)[0][1]!='T':
            raise ValueError('Candidate strong/retained weak pose binding failed')
        abi=subprocess.check_output(['file',str(exe),str(lib)],text=True);deps=subprocess.check_output(['ldd',str(exe)],text=True)
        if abi.count('ARM aarch64')!=2 or 'not found' in deps or str(lib) not in deps:raise ValueError('Native ELF/dependency check failed')
        if digest(source)!=state['source_sha256'] or any(digest(p)!=h for p,h in before.items()):
            raise ValueError('Retained sources or build products changed')
        state.update(status='NATIVE_POSE_CANDIDATE_BUILD_PASS',architecture=abi,dependencies=deps,
                     products_sha256={str(p):digest(p) for p in (exe,lib)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:state['finished_monotonic_ns']=time.monotonic_ns();save()
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
