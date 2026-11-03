"""Native link of one hash-verified cross object, retaining the PS adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest
from .build_pose_variant import extract,symbols


def run(root,adapter,entry,cross,output):
    root,adapter,entry,cross,output=map(lambda p:Path(p).resolve(),(root,adapter,entry,cross,output))
    if platform.machine()!='aarch64':raise ValueError('Actual native KV260 link required')
    base=json.loads((adapter/'BUILD.json').read_text());main=json.loads((entry/'BUILD.json').read_text())
    proof=json.loads((cross/'CROSS_COMPILE.json').read_text());obj=cross/'PoseOptimization.o'
    if proof['status']!='CROSS_OBJECT_COMPILED_REQUIRES_NATIVE_LINK_AND_BOARD_GATES' or digest(obj)!=proof['object_sha256']:
        raise ValueError('Cross object status/hash mismatch')
    variant=proof.get('variant','compiler-only')
    if variant not in ('compiler-only','quadratic'):raise ValueError('Unreviewed cross pose variant')
    if variant=='quadratic':
        numerical=proof.get('equation_proof') or {}
        if numerical.get('status')!='INDEPENDENT_NUMPY_QUADRATIC_PASS' or numerical.get('cases')!=256 or numerical.get('max_normalized_error',1)>1e-12:
            raise ValueError('Independent quadratic equation gate not passed')
        for name in ('PoseQuadratic.h','FastPoseQuadratic.h'):
            if digest(cross/name)!=digest(Path(__file__).parent/name):
                raise ValueError('Numerically checked quadratic header changed')
        if digest(cross/'PoseOptimization.cc')!=proof['private_source_sha256']:
            raise ValueError('Cross private source changed')
    source=root/'slam/src/Optimizer.cc';_,body=extract(source.read_bytes().decode())
    if digest(source)!=proof['source_sha256'] or hashlib.sha256(body.encode()).hexdigest()!=proof['function_sha256']:
        raise ValueError('Cross/native source mismatch')
    for d in (base,main):
        for p,h in d['products_sha256'].items():
            if digest(p)!=h:raise ValueError('Retained product changed')
    original=root/'build/CMakeFiles/ORB_SLAM3.dir/src/Optimizer.cc.o';symbol=symbols(original)
    if len(symbol)!=1 or symbol[0][1]!='T' or symbols(obj)[0][2]!=symbol[0][2]:raise ValueError('Pose object ABI mismatch')
    output.mkdir(parents=True,exist_ok=False);(output/'lib').mkdir();(output/'bin').mkdir()
    weak=output/'RetainedOptimizer.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink=list(base['commands'][1]);old='CMakeFiles/ORB_SLAM3.dir/src/Optimizer.cc.o'
    if liblink.count(old)!=1:raise ValueError('Original optimizer link mismatch')
    liblink[liblink.index(old)]=str(weak);liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(obj));liblink[liblink.index('-o')+1]=str(lib)
    exelink=list(main['commands'][1]);oldlib=str(adapter/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Original executable link mismatch')
    exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    state=dict(status='RUNNING',scope='Native link only; full functional, numerical and physical video gates remain separate',
               cross=proof,commands=[['objcopy','--weaken-symbol='+symbol[0][2],str(original),str(weak)],liblink,exelink])
    try:
        with (output/'build.log').open('w') as log:
            for command in state['commands']:subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'undefined symbol' in deps or 'not found' in deps or str(lib) not in deps or symbols(lib,True)[0][1]!='T':
            raise ValueError('Native symbol/dependency check failed')
        for d in (base,main):
            for p,h in d['products_sha256'].items():
                if digest(p)!=h:raise ValueError('Retained product changed')
        state.update(status='NATIVE_CROSS_POSE_LINK_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','entry','cross','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
