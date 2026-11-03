"""Native keyframe cadence composition, protecting every retained strong function."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest
from .compile_keyframe_cadence import extract
from .compose_local_ba import strongs

SYMBOL='_ZN9ORB_SLAM38Tracking15NeedNewKeyFrameEv'


def run(root,base,cross,output):
    root,base,cross,output=map(lambda p:Path(p).resolve(),(root,base,cross,output))
    if platform.machine()!='aarch64':raise ValueError('Actual KV260 linker required')
    old=json.loads((base/'BUILD.json').read_text());proof=json.loads((cross/'CROSS_COMPILE.json').read_text())
    if old['status']!='NATIVE_LOCAL_BA_COMPOSITION_PASS' or proof['status']!='CROSS_KEYFRAME_CADENCE_COMPILED_REQUIRES_NATIVE_GATES':raise ValueError('Explicit graph and cadence builds required')
    source=root/'slam/src/Tracking.cc';private,body=extract(source.read_bytes().decode(),proof['interval'])
    obj=cross/'NeedNewKeyFrame.o';retained=root/'build/CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o'
    if digest(source)!=proof['source_sha256'] or hashlib.sha256(body.encode()).hexdigest()!=proof['function_sha256'] or (cross/'NeedNewKeyFrame.cc').read_bytes()!=private.encode() or digest(obj)!=proof['object_sha256']:raise ValueError('Cadence source/object mismatch')
    if strongs(retained).get(SYMBOL)!='T' or strongs(obj).get(SYMBOL)!='T':raise ValueError('Cadence strong ABI mismatch')
    relocs=subprocess.check_output(['readelf','-rW',str(retained)],text=True)
    calls=[s for s in relocs.splitlines() if 'R_AARCH64_CALL26' in s and SYMBOL in s]
    if len(calls)!=1:raise ValueError('Expected actual retained tracking call, no inlined bypass')
    before={**old['products_sha256'],str(source):digest(source),str(retained):digest(retained)}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/products changed')
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('lib','bin'):(output/folder).mkdir()
    weak=output/'RetainedTracking.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink=list(old['commands'][-2]);slot='CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o'
    if liblink.count(slot)!=1:raise ValueError('Retained tracking link mismatch')
    liblink[liblink.index(slot)]=str(weak);liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(obj));liblink[liblink.index('-o')+1]=str(lib)
    exelink=list(old['commands'][-1]);oldlib=str(base/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Selected library link mismatch')
    exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands=[['objcopy','--weaken-symbol='+SYMBOL,str(retained),str(weak)],liblink,exelink]
    state=dict(status='RUNNING',scope='Changed monocular minimum keyframe spacing; all video/feature/pose frames retained, native quality/performance not inferred',
               interval=proof['interval'],neighbors=old['neighbors'],cross=proof,commands=commands,protected_sha256=before,retained_call_relocations=calls)
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        if strongs(weak)!={**strongs(retained),SYMBOL:'W'} or strongs(lib).get(SYMBOL)!='T':raise ValueError('Unexpected retained tracking symbol change')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Native cadence dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/products modified')
        state.update(status='NATIVE_KEYFRAME_CADENCE_COMPOSITION_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('root','base','cross','output'):p.add_argument('--'+n,type=Path,required=True)
    run(**vars(p.parse_args()))
