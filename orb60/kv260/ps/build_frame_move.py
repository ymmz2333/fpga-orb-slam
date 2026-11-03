"""Compose verified Frame ownership transfer with unchanged tracking source."""
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
from .check_frame_move import transform
from .compose_local_ba import strongs


def run(root,adapter,base,library_base,component,output):
    root,adapter,base,library_base,component,output=map(lambda p:Path(p).resolve(),(root,adapter,base,library_base,component,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 with compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());library=json.loads((library_base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text());proof=json.loads((component/'COMPONENT.json').read_text())
    if old['status']!='NATIVE_PACKED_BMP_COMPONENT_PASS' or library['status']!='NATIVE_PACKED_ARM_CRC_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit retained input/library base required')
    if proof['status']!='EXACT_FRAME_MOVE_COMPONENT_PASS' or not proof['beneficial_microbenchmark'] or len(proof['runs'])!=4 or len({r['sha256'] for r in proof['runs']})!=1:raise ValueError('Exact ownership and native benchmark gates required')
    for row in proof['runs']:
        if digest(component/row['file'])!=row['sha256'] or row['report']['cases']!=128:raise ValueError('Frame component evidence changed')
    header=root/'slam/include/Frame.h';tracking=root/'slam/src/Tracking.cc';changed=transform(header.read_text())
    if digest(tracking)!='38e4fb1594c7d4f6e4fa2676ad4c3c508221b1daaee41cbe6d287257e073c7ae' or changed!=(component/'candidate/Frame.h').read_text() or digest(component/'candidate/Frame.h')!=proof['header_sha256']:raise ValueError('Unreviewed Frame/Tracking source')
    liblink=list(library['link_commands']['library']);mainlink=list(old['link_commands']['executable'])
    slots=[i for i,x in enumerate(liblink) if x.endswith('/src/Tracking.cc.o')]
    libslots=[i for i,x in enumerate(mainlink) if x.endswith('/libORB_SLAM3.so')]
    if len(slots)!=1 or len(libslots)!=1 or mainlink[libslots[0]]!=str(library_base/'lib/libORB_SLAM3.so'):raise ValueError('Unreviewed selected tracking/library link')
    before={**old['products_sha256'],**library['products_sha256'],**proof['products_sha256'],str(header):digest(header),str(tracking):digest(tracking),str(component/'COMPONENT.json'):digest(component/'COMPONENT.json')}
    for command in (liblink,mainlink):
        for value in command:
            if value.endswith('.o'):
                path=Path(value);path=path if path.is_absolute() else root/'build'/path
                before[str(path)]=digest(path)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/object modified')
    output.mkdir(parents=True,exist_ok=False)
    for n in ('source','lib','bin'):(output/n).mkdir()
    for p in (base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/Frame.h').write_text(changed);(output/'source/Tracking.cc').write_bytes(tracking.read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=[common[0],'-I'+str(output/'source'),'-include',str(output/'source/Frame.h'),*common[1:]]
    obj=output/'Tracking.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    original=Path(liblink[slots[0]]);original=original if original.is_absolute() else root/'build'/original
    liblink[slots[0]]=str(obj);liblink[liblink.index('-o')+1]=str(lib)
    mainlink[libslots[0]]=str(lib);mainlink[mainlink.index('-o')+1]=str(exe)
    for i,x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):mainlink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands=[[*common,'-c',str(output/'source/Tracking.cc'),'-o',str(obj)],liblink,mainlink]
    state=dict(status='RUNNING',scope='PS C++ temporary assignment storage transfer only. Tracking.cc bytes and every solver/matcher/PL/DPU object unchanged; native whole-video acceptance still required.',
               protected_sha256=before,component_proof_sha256=digest(component/'COMPONENT.json'),tracking_body_unchanged=True,
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,link_commands=dict(library=liblink,executable=mainlink))
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own compile stopped below256MiB available')
                        time.sleep(.5)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
        old_symbols={k:v for k,v in strongs(original).items() if v=='T'};new_symbols={k:v for k,v in strongs(obj).items() if v=='T'}
        if old_symbols!=new_symbols:raise ValueError('Unexpected strong tracking ABI change')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Native Frame candidate dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained object changed')
        state.update(status='NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS',tracking_strong_symbols=len(new_symbols),dependencies=deps,
                     products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],tracking_strong_symbols=state['tracking_strong_symbols'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','library_base','component','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
