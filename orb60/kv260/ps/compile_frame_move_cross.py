"""PC-only ARM object build from frozen board headers; native gates follow."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import signal
import os
import subprocess
import time
from .build_network_adapter import digest


def run(compiler,sysroot,inputs,output,variant='frame-move',board_output=None):
    compiler,sysroot,inputs,output=map(lambda p:Path(p).resolve(),(compiler,sysroot,inputs,output))
    if platform.machine()!='x86_64' or subprocess.check_output([str(compiler),'-dumpmachine'],text=True).strip()!='aarch64-none-linux-gnu':raise ValueError('Reviewed PC AArch64 cross compiler required')
    version=subprocess.check_output([str(compiler),'--version'],text=True)
    if not subprocess.check_output([str(compiler),'-dumpversion'],text=True).strip().startswith('11'):raise ValueError('Reviewed GCC11 required')
    manifest=json.loads((inputs/'FRAME_CROSS_INPUTS_20261103_A.json').read_text())
    if any(digest(inputs/n)!=v['sha256'] for n,v in manifest.items()):raise ValueError('Frozen board input changed')
    native=json.loads((inputs/'BUILD_NATIVE_FAILED.json').read_text());command=native['commands'][0];old=command[1:command.index('-c')]
    source_dir=Path(manifest['source/Tracking.cc']['board_path']).parent;board_root=source_dir.parents[1]
    flags=[];dropped=[];i=0
    while i<len(old):
        x=old[i]
        if x.startswith('-I'):
            p=Path(x[2:])
            if p==source_dir:flags.append('-I'+str(inputs/'source'))
            elif p==board_root/'slam' or board_root/'slam' in p.parents:flags.append('-I'+str(inputs/'project'/p.relative_to(board_root)))
            elif p.name=='source' and board_root in p.parents:dropped.append(str(p))
            else:raise ValueError('Unreviewed project include '+str(p))
        elif x=='-isystem':
            i+=1;p=Path(old[i])
            if Path('/usr/include') not in p.parents:raise ValueError('Unreviewed native system include')
            flags+=['-isystem',str(sysroot/str(p).lstrip('/'))]
        elif x=='-include':
            i+=1
            if Path(old[i])!=source_dir/'Frame.h':raise ValueError('Unreviewed forced header')
            flags+=['-include',str(inputs/'source/Frame.h')]
        else:flags.append(x)
        i+=1
    if '-O2' not in flags or any(x in flags for x in ('-ffast-math','-Ofast','-O3')):raise ValueError('Retained tracking optimization flags required')
    standard=[sysroot/'usr/include/c++/11',sysroot/'usr/include/aarch64-linux-gnu/c++/11',sysroot/'usr/include/c++/11/backward']
    if not all(p.is_dir() for p in standard):raise ValueError('Captured board C++11 headers required')
    prefix=[str(compiler),'--sysroot='+str(sysroot),'-nostdinc++']
    for p in standard:prefix+=['-isystem',str(p)]
    prefix+=['-isystem',str(sysroot/'usr/include/aarch64-linux-gnu')]
    if variant not in ('frame-move','defer-strong-motion'):raise ValueError('Explicit reviewed PS variant required')
    if variant!='frame-move' and (not board_output or not Path(board_output).is_absolute()):raise ValueError('Explicit board path for private policy source required')
    output.mkdir(parents=True,exist_ok=False);commands=[]
    state=dict(status='RUNNING',scope='PC compilation only. Matching board dependencies, native ABI/semantic replay, native link and actual DPU system gates remain required.',compiler=version,compiler_sha256=digest(compiler),inputs_manifest_sha256=digest(inputs/'FRAME_CROSS_INPUTS_20261103_A.json'),dropped_private_adapter_includes=dropped,commands=commands,dependencies={},products_sha256={})
    def save():(output/'CROSS_COMPILE.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    tracking=inputs/'source/Tracking.cc'
    state['variant']=variant
    if variant=='defer-strong-motion':
        from .motion_pose_transform import transform
        tracking=output/'Tracking.cc';tracking.write_text(transform((inputs/'source/Tracking.cc').read_text()))
        header=Path(__file__).with_name('MotionPosePolicy.h');(output/header.name).write_bytes(header.read_bytes())
        flags=['-I'+str(output),*flags]
        state.update(scope='PC-compiled PS candidate defers only preliminary strong mono motion solves; final pose/thresholds and Frame layout retained. Actual numerical/quality/performance gates remain required.',board_output=str(board_output),private_tracking_sha256=digest(tracking),policy_header_sha256=digest(header))
    jobs=[('Tracking',tracking,flags)]
    unit_flags=[];i=0
    while i<len(flags):
        if flags[i]=='-include':i+=2;continue
        unit_flags.append(flags[i]);i+=1
    unit_flags=['-I'+str(inputs/'component/candidate'),*unit_flags,'-DFRAME_MOVE_CANDIDATE=1']
    jobs += [('FrameCheck',inputs/'component/check_frame_move.cc',unit_flags),('FrameABI',inputs/'component/candidate/frame_abi.cc',unit_flags)]
    try:
        with (output/'build.log').open('w') as log:
            for name,source,options in jobs:
                obj=output/(name+'.o');dep=output/(name+'.d');resource=output/(name+'_resources.txt')
                cmd=[*prefix,*options,'-MD','-MF',str(dep),'-c',str(source),'-o',str(obj)];commands.append(cmd);state['current']=name;save()
                child=subprocess.Popen(['/usr/bin/time','-v','-o',str(resource),*cmd],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        avail=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))
                        if avail<1024*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own cross compiler stopped below1GiB available')
                        time.sleep(.5)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,cmd)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
                abi=subprocess.check_output(['file',str(obj)],text=True)
                if 'ARM aarch64' not in abi:raise ValueError('Cross object architecture mismatch')
                state['products_sha256'][obj.name]=digest(obj)
                for value in shlex.split(dep.read_text().replace('\\\n','').split(':',1)[1]):
                    p=Path(value).resolve();item=dict(sha256=digest(p))
                    if inputs in p.parents:
                        key=str(p.relative_to(inputs))
                        if key not in manifest:raise ValueError('Unsealed source dependency: '+key)
                        item['board_path']=manifest[key]['board_path']
                    elif output in p.parents and variant=='defer-strong-motion':item['board_path']=str(Path(board_output)/p.relative_to(output))
                    elif sysroot in p.parents:item['board_path']='/'+str(p.relative_to(sysroot))
                    else:item['toolchain_builtin']=True
                    state['dependencies'][str(p)]=item
                print('CROSS_FRAME_OBJECT',name,state['products_sha256'][obj.name],flush=True);save()
        state.update(status='CROSS_FRAME_OBJECTS_COMPILED_REQUIRES_NATIVE_GATES' if variant=='frame-move' else 'CROSS_MOTION_POLICY_COMPILED_REQUIRES_NATIVE_GATES',current=None)
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:save()
    print(json.dumps(dict(status=state['status'],objects=len(state['products_sha256']),dependencies=len(state['dependencies']))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('compiler','sysroot','inputs','output'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--variant',choices=['frame-move','defer-strong-motion'],default='frame-move');p.add_argument('--board-output')
    run(**vars(p.parse_args()))
