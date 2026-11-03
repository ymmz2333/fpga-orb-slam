"""Compose native packed YUYV/UYVY input with the unchanged PS SLAM library."""
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


def transform(main):
    anchor='const std::string out=argv[6];'
    insert='const std::string input_format=std::string(argv[3]).compare(0,5,"yuyv:")==0?"YUYV":(std::string(argv[3]).compare(0,5,"uyvy:")==0?"UYVY":"");require(!input_format.empty(),"Explicit packed YUYV/UYVY input required");'+anchor
    a='\\"native_color_preview\\"';b='\\"input_format\\":\\""<<input_format<<"\\",'+a
    if main.count(anchor)!=1 or main.count(a)!=1:raise ValueError('Unreviewed native packed input/report boundary')
    out=main.replace(anchor,insert).replace(a,b)
    if out.replace(insert,anchor).replace(b,a)!=main:raise ValueError('Unexpected native packed tracking change')
    return out


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_DIRECT_GRAY_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit direct-gray base required')
    link=list(old['link_commands']['executable']);slots=[i for i,x in enumerate(link) if x.endswith('/network.o')]
    if len(slots)!=1:raise ValueError('Unreviewed main object link')
    source=base/'source/mono_kv260_network.cc';before={**old['products_sha256'],**flags['products_sha256'],str(source):digest(source)}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained products changed')
    entry=transform(source.read_text());output.mkdir(parents=True,exist_ok=False)
    for name in ('source','bin'):(output/name).mkdir()
    for p in (base/'source').glob('*.h'):(output/'source'/p.name).write_bytes(p.read_bytes())
    for name in ('PackedYuvSource.h','Kv260VideoPipeline.h'):(output/'source'/name).write_bytes((Path(__file__).parent/name).read_bytes())
    (output/'source/mono_kv260_network.cc').write_text(entry)
    common=list(flags['commands'][0]);common=common[:common.index('-c')];common=[common[0],'-I'+str(output/'source'),*common[1:]]
    obj=output/'network.o';exe=output/'bin/mono_kv260_network';link[slots[0]]=str(obj);link[link.index('-o')+1]=str(exe)
    commands=[[*common,'-c',str(output/'source/mono_kv260_network.cc'),'-o',str(obj)],link]
    state=dict(status='RUNNING',scope='Native uncompressed packed file read, luminance LUT and BGR conversion included; no compressed decoder. SLAM math/graph/library unchanged. Actual camera capture is separate',
               formats=['YUYV','UYVY'],protected_sha256=before,source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,link_commands=dict(executable=link))
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
        lib=[Path(p) for p in old['products_sha256'] if Path(p).name=='libORB_SLAM3.so']
        if len(lib)!=1:raise ValueError('Selected SLAM library ambiguous')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib[0]) not in deps:raise ValueError('Packed native dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained product modified')
        state.update(status='NATIVE_PACKED_YUV_COMPONENT_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (exe,lib[0])})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','output'):p.add_argument('--'+k,type=Path,required=True)
    run(**vars(p.parse_args()))
