"""Isolated native PS mapper scheduling candidate, preserving retained objects."""
import argparse
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import available


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and1536MiB available required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_NEON_DISTANCE_CANDIDATE_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit verified base builds required')
    before={**old['products_sha256'],**flags['products_sha256']}
    for rel in ('slam/src/System.cc','slam/include/System.h','build/CMakeFiles/ORB_SLAM3.dir/src/System.cc.o'):
        p=root/rel;before[str(p)]=digest(p)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained base changed')
    header=(root/'slam/include/System.h').read_text();anchor='private:\n\n    void SaveAtlas'
    if header.count(anchor)!=1:raise ValueError('Unreviewed public System API boundary')
    header=header.replace(anchor,'double WaitForLocalMapping(unsigned timeout_ms);\n\n'+anchor)
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','lib','bin'):(output/folder).mkdir()
    authored=Path(__file__).parent
    (output/'source/System.h').write_text(header)
    original_system=(root/'slam/src/System.cc').read_bytes()
    (output/'source/System.cc').write_bytes(original_system+b'\n#include "MapperBarrier.inc"\n')
    for name in ('MapperBarrier.inc','mono_kv260_network.cc'):(output/'source'/name).write_bytes((authored/name).read_bytes())
    common=flags['commands'][0][:flags['commands'][0].index('-c')]
    # Retain the private FeatureIO/video headers. Only System.h resolves first
    # from this generated directory; no original header or source is overwritten.
    common=[common[0],'-I'+str(output/'source'),*common[1:]]
    system_obj=output/'System.o';main_obj=output/'network.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    commands=[[*common,'-c',str(output/'source/System.cc'),'-o',str(system_obj)],
              [*common,'-DORB60_ENABLE_MAPPER_BARRIER','-c',str(output/'source/mono_kv260_network.cc'),'-o',str(main_obj)]]
    liblink=list(old['commands'][3]);slot='CMakeFiles/ORB_SLAM3.dir/src/System.cc.o'
    if liblink.count(slot)!=1:raise ValueError('Original System link mismatch')
    liblink[liblink.index(slot)]=str(system_obj);liblink[liblink.index('-o')+1]=str(lib);commands.append(liblink)
    exelink=list(old['commands'][4]);oldlib=str(base/'lib/libORB_SLAM3.so')
    mains=[i for i,x in enumerate(exelink) if x.endswith('/network.o')]
    if len(mains)!=1 or exelink.count(oldlib)!=1:raise ValueError('Original entry link mismatch')
    exelink[mains[0]]=str(main_obj);exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands.append(exelink)
    state=dict(status='RUNNING',scope='PS scheduling diagnostic only; all geometry thresholds retained, waits included in whole FPS',
               commands=commands,protected_sha256=before,source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},
               original_system_body_prefix_unchanged=True)
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own native compile stopped below256MiB available')
                        time.sleep(1)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Mapper candidate dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained sources/objects changed')
        state.update(status='NATIVE_MAPPER_SCHEDULING_CANDIDATE_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','base','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
