"""Native link of the numerically gated FP64 kernel into an explicit PS candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest
from .build_pose_variant import extract,symbols


def run(root,base,cross,output):
    root,base,cross,output=map(lambda p:Path(p).resolve(),(root,base,cross,output))
    if platform.machine()!='aarch64':raise ValueError('Native KV260 link required')
    old=json.loads((base/'BUILD.json').read_text());proof=json.loads((cross/'CROSS_COMPILE.json').read_text())
    if old['status'] not in ('NATIVE_MAPPER_SCHEDULING_CANDIDATE_PASS','NATIVE_MAPPER_PUBLICATION_CANDIDATE_PASS'):
        raise ValueError('Explicit mapper candidate required')
    numerical=proof.get('equation_proof') or {}
    if proof['status']!='CROSS_OBJECT_COMPILED_REQUIRES_NATIVE_LINK_AND_BOARD_GATES' or proof.get('variant')!='quadratic-neon' or numerical.get('status')!='INDEPENDENT_NATIVE_NEON_QUADRATIC_PASS':
        raise ValueError('Actual A53 and independent FP64 equation gates required')
    if numerical.get('native_machine')!='aarch64' or set(numerical.get('layouts',{}))!={'col','row'} or any(x.get('max_normalized_error',1)>1e-12 for x in numerical['layouts'].values()):
        raise ValueError('Incomplete numerical layout gates')
    for name in ('PoseQuadraticNeon.h','FastPoseQuadraticNeon.h'):
        if digest(cross/name)!=digest(Path(__file__).parent/name) or proof['authored_header_sha256'].get(name)!=digest(cross/name):
            raise ValueError('Selected numerical kernel header changed')
    obj=cross/'PoseOptimization.o'
    if digest(obj)!=proof['object_sha256'] or digest(cross/'PoseOptimization.cc')!=proof['private_source_sha256']:
        raise ValueError('Cross numerical object/source mismatch')
    original=root/'slam/src/Optimizer.cc';_,body=extract(original.read_bytes().decode())
    if digest(original)!=proof['source_sha256'] or hashlib.sha256(body.encode()).hexdigest()!=proof['function_sha256']:
        raise ValueError('Retained pose source mismatch')
    if len(symbols(obj))!=1 or symbols(obj)[0][1]!='T':raise ValueError('Expected one strong cross pose definition')
    before=old['products_sha256']
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Selected mapper products changed')
    output.mkdir(parents=True,exist_ok=False);(output/'lib').mkdir();(output/'bin').mkdir()
    lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink=list(old['commands'][-2]);pose=[i for i,x in enumerate(liblink) if x.endswith('/PoseOptimization.o')]
    if len(pose)!=1:raise ValueError('Selected mapper pose object link mismatch')
    liblink[pose[0]]=str(obj);liblink[liblink.index('-o')+1]=str(lib)
    exelink=list(old['commands'][-1]);oldlib=str(base/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Selected mapper library link mismatch')
    exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    state=dict(status='RUNNING',scope='Native composition only; actual whole source/SLAM/DPU/cloud/GPU gates remain required',
               commands=[liblink,exelink],cross=proof,base_build_sha256=digest(base/'BUILD.json'),protected_sha256=before)
    try:
        with (output/'build.log').open('w') as log:
            for command in state['commands']:subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps or symbols(lib,True)[0][1]!='T':raise ValueError('Native composition link failed')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained mapper products modified')
        state.update(status='NATIVE_NEON_POSE_COMPOSITION_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','base','cross','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
