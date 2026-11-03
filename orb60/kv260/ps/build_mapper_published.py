"""PS publication-only handoff candidate; retains background local optimization."""
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
    if old['status']!='NATIVE_NEON_DISTANCE_CANDIDATE_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Verified explicit base required')
    before={**old['products_sha256'],**flags['products_sha256']}
    source=root/'slam/src/LocalMapping.cc';original=root/'build/CMakeFiles/ORB_SLAM3.dir/src/LocalMapping.cc.o'
    before.update({str(p):digest(p) for p in (source,original)})
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained products changed')
    text=source.read_text();header='#include "LocalMapping.h"';push='mlNewKeyFrames.push_back(pKF);';process='CreateNewMapPoints();'
    if any(text.count(x)!=1 for x in (header,push,process)):raise ValueError('Unreviewed mapper insertion/processing boundaries')
    hnew=header+'\n#include "KvMapperProgress.h"'
    pnew='KvMapperProgress::submitted(pKF);\n    '+push
    cnew=process+'\n            KvMapperProgress::published(mpCurrentKeyFrame);'
    changed=text.replace(header,hnew).replace(push,pnew).replace(process,cnew)
    if changed.replace(hnew,header).replace(pnew,push).replace(cnew,process)!=text:raise ValueError('Unexpected mapper body change')
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','lib','bin'):(output/folder).mkdir()
    (output/'source/LocalMapping.cc').write_text(changed)
    authored=Path(__file__).parent
    for name in ('KvMapperProgress.h','KvMapperProgress.cc','check_mapper_progress.cc','mono_kv260_network.cc'):
        (output/'source'/name).write_bytes((authored/name).read_bytes())
    common=flags['commands'][0][:flags['commands'][0].index('-c')]
    common=[common[0],'-I'+str(output/'source'),*common[1:]]
    mapper_obj=output/'LocalMapping.o';progress_obj=output/'KvMapperProgress.o';main_obj=output/'network.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network';check=output/'bin/check_mapper_progress'
    unit=[common[0],'-O2','-std=gnu++14','-pthread','-DKV_MAPPER_PROGRESS_TEST',str(output/'source/KvMapperProgress.cc'),str(output/'source/check_mapper_progress.cc'),'-o',str(check)]
    commands=[unit,[*common,'-c',str(output/'source/KvMapperProgress.cc'),'-o',str(progress_obj)],
              [*common,'-c',str(output/'source/LocalMapping.cc'),'-o',str(mapper_obj)],
              [*common,'-DORB60_ENABLE_MAPPER_PUBLISHED','-c',str(output/'source/mono_kv260_network.cc'),'-o',str(main_obj)]]
    liblink=list(old['commands'][3]);slot='CMakeFiles/ORB_SLAM3.dir/src/LocalMapping.cc.o'
    if liblink.count(slot)!=1:raise ValueError('Original LocalMapping object link mismatch')
    liblink[liblink.index(slot)]=str(mapper_obj);liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(progress_obj));liblink[liblink.index('-o')+1]=str(lib);commands.append(liblink)
    exelink=list(old['commands'][4]);oldlib=str(base/'lib/libORB_SLAM3.so');mains=[i for i,x in enumerate(exelink) if x.endswith('/network.o')]
    if len(mains)!=1 or exelink.count(oldlib)!=1:raise ValueError('Original executable link mismatch')
    exelink[mains[0]]=str(main_obj);exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands.append(exelink)
    state=dict(status='RUNNING',scope='PS handoff after actual CreateNewMapPoints completion; neighbor fusion and local optimization remain concurrent; no geometry gate changes',
               commands=commands,protected_sha256=before,source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},
               mapper_math_unchanged_outside_two_event_hooks=True)
    try:
        with (output/'build.log').open('w') as log:
            for i,command in enumerate(commands):
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Owned compiler stopped below256MiB available')
                        time.sleep(1)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
                if i==0:
                    proof=subprocess.check_output([str(check)],text=True)
                    if proof.strip()!='MAPPER_PUBLICATION_PROTOCOL_PASS':raise ValueError('Native handoff unit gate failed')
                    state['native_protocol_gate']=proof.strip()
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Published mapper dependency mismatch')
        if 'reset_for_test' in subprocess.check_output(['nm','-g',str(progress_obj)],text=True):raise ValueError('Test reset exported in production object')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained products modified')
        state.update(status='NATIVE_MAPPER_PUBLICATION_CANDIDATE_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe,check)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','base','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
