"""PC/WSL cross compile only; native link, numerical and board gates are separate."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import extract


def run(compiler,sysroot,adapter_build,output,variant='compiler-only',equation_proof=None):
    compiler,sysroot,adapter_build,output=map(lambda p:Path(p).resolve(),(compiler,sysroot,adapter_build,output))
    if platform.machine()!='x86_64':raise ValueError('PC cross-build host required')
    target=subprocess.check_output([str(compiler),'-dumpmachine'],text=True).strip()
    if target!='aarch64-none-linux-gnu':raise ValueError('Explicit AArch64 Linux target required')
    version=subprocess.check_output([str(compiler),'--version'],text=True)
    if not subprocess.check_output([str(compiler),'-dumpversion'],text=True).strip().startswith('11'):
        raise ValueError('Reviewed GCC11 toolchain required')
    base=json.loads(adapter_build.read_text());native=next(Path(k).parents[2] for k in base['products_sha256'] if k.endswith('libORB_SLAM3.so'))
    old=base['commands'][0];old=old[1:old.index('-c')];flags=[];i=0
    while i<len(old):
        item=old[i]
        if item.startswith('-I'):
            p=Path(item[2:])
            if (native/'slam')==p or (native/'slam') in p.parents:flags.append('-I'+str(sysroot/p.relative_to(native)))
            elif p.name!='source':raise ValueError('Unreviewed native include: '+str(p))
        elif item=='-isystem':
            i+=1;p=Path(old[i])
            if Path('/usr/include') not in p.parents:raise ValueError('Unreviewed system include')
            flags+=['-isystem',str(sysroot/str(p).lstrip('/'))]
        else:flags.append('-O3' if item=='-O2' else item)
        i+=1
    if any(x in flags for x in ('-ffast-math','-Ofast')):raise ValueError('Unreviewed floating point relaxation')
    standard=[sysroot/'usr/include/c++/11',sysroot/'usr/include/aarch64-linux-gnu/c++/11',sysroot/'usr/include/c++/11/backward']
    if not all(p.is_dir() for p in standard):raise ValueError('Actual board GCC11 headers required')
    source=sysroot/'slam/src/Optimizer.cc';private,body=extract(source.read_bytes().decode())
    proof=None
    if variant in ('quadratic','quadratic-neon'):
        if equation_proof is None:raise ValueError('Independent equation proof required')
        proof=json.loads(Path(equation_proof).read_text())
        if variant=='quadratic':
            if proof.get('status')!='INDEPENDENT_NUMPY_QUADRATIC_PASS' or proof.get('cases')!=256 or proof.get('max_normalized_error',1)>1e-12:
                raise ValueError('Independent equation gate failed')
        else:
            if proof.get('status')!='INDEPENDENT_NATIVE_NEON_QUADRATIC_PASS' or proof.get('native_machine')!='aarch64' or proof.get('header_sha256')!=digest(Path(__file__).parent/'PoseQuadraticNeon.h'):
                raise ValueError('Actual A53 and independent NEON equation gates required')
            if set(proof.get('layouts',{}))!={'col','row'} or any(v.get('cases')!=256 or v.get('max_normalized_error',1)>1e-12 for v in proof['layouts'].values()):
                raise ValueError('Both independent Jacobian layout checks required')
        retained=(sysroot/'slam/Thirdparty/g2o/g2o/core/base_edge.h').read_text()
        if 'InformationType result = rho[1] * _information;' not in retained or '//result.noalias() += 2 * rho[2]' not in retained:
            raise ValueError('Unreviewed retained robust information model')
        for name,count in (('EdgeSE3ProjectXYZOnlyPose',2),('EdgeSE3ProjectXYZOnlyPoseToBody',1)):
            old='new ORB_SLAM3::'+name+'()'
            if private.count(old)!=count:raise ValueError('Ambiguous mono pose edge replacement')
            private=private.replace(old,'new KvPose::Edge<ORB_SLAM3::'+name+'>()')
        edge_header='FastPoseQuadraticNeon.h' if variant=='quadratic-neon' else 'FastPoseQuadratic.h'
        private=private.replace('namespace ORB_SLAM3 {','\n#include "'+edge_header+'"\nnamespace ORB_SLAM3 {',1)
        flags=['-O2' if x=='-O3' else x for x in flags]
        flags+=['-ffp-contract=off','-fvisibility-inlines-hidden']
    elif variant!='compiler-only':raise ValueError('Unreviewed pose variant')
    output.mkdir(parents=True,exist_ok=False);(output/'PoseOptimization.cc').write_bytes(private.encode())
    if variant in ('quadratic','quadratic-neon'):
        headers=('FastPoseQuadraticNeon.h','PoseQuadraticNeon.h') if variant=='quadratic-neon' else ('FastPoseQuadratic.h','PoseQuadratic.h')
        for name in headers:
            (output/name).write_bytes((Path(__file__).parent/name).read_bytes())
    command=[str(compiler),'--sysroot='+str(sysroot),'-nostdinc++']
    for p in standard:command+=['-isystem',str(p)]
    command+=['-isystem',str(sysroot/'usr/include/aarch64-linux-gnu'),*flags,'-mcpu=cortex-a53',
              '-c',str(output/'PoseOptimization.cc'),'-o',str(output/'PoseOptimization.o')]
    state=dict(status='RUNNING',scope='PC cross object only, no hardware or performance acceptance',target=target,
               compiler=version,compiler_sha256=digest(compiler),command=command,source_sha256=digest(source),
               function_sha256=hashlib.sha256(body.encode()).hexdigest(),function_body_unchanged=variant=='compiler-only',fast_math=False,
               variant=variant,equation_proof=proof,private_source_sha256=digest(output/'PoseOptimization.cc'),
               authored_header_sha256={p.name:digest(p) for p in output.glob('*.h')},
               replacement_scope='two mono unary-edge quadratic products' if variant in ('quadratic','quadratic-neon') else 'compiler flags only',
               started_monotonic_ns=time.monotonic_ns())
    def save():(output/'CROSS_COMPILE.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        with (output/'build.log').open('w') as log:
            subprocess.run(['/usr/bin/time','-v','-o',str(output/'resources.txt'),*command],stdout=log,stderr=subprocess.STDOUT,check=True)
        abi=subprocess.check_output(['file',str(output/'PoseOptimization.o')],text=True)
        if 'ARM aarch64' not in abi:raise ValueError('Wrong object architecture')
        state.update(status='CROSS_OBJECT_COMPILED_REQUIRES_NATIVE_LINK_AND_BOARD_GATES',architecture=abi,
                     object_sha256=digest(output/'PoseOptimization.o'))
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:state['finished_monotonic_ns']=time.monotonic_ns();save()
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('compiler','sysroot','adapter-build','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--variant',choices=('compiler-only','quadratic','quadratic-neon'),default='compiler-only')
    p.add_argument('--equation-proof',type=Path)
    run(**vars(p.parse_args()))
