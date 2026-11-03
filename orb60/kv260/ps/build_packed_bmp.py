"""Compose uncompressed input with lossless PS RGB handoff and RAM preview."""
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
from .build_bmp_preview import transform as preview_transform


def color_cache_transform(main):
    start='void publish_rgb('
    end='\n}\n}\nint main('
    if main.count(start)!=1 or main.count(end)!=1:raise ValueError('Unreviewed native RGB cache boundary')
    a=main.index(start);b=main.index(end,a)+2;old=main[a:b];new=old
    substitutions=[
        ('cv::imencode(".png",frame.bgr,png,{cv::IMWRITE_PNG_COMPRESSION,1})','cv::imencode(".bmp",frame.bgr,bmp)'),
        ('std::vector<uint8_t> png;','std::vector<uint8_t> bmp;'),
        ('png.data()','bmp.data()'),('png.size()','bmp.size()'),
        ('+".png','+".bmp'),('<<".png','<<".bmp'),('RGB PNG','RGB BMP')]
    for x,y in substitutions:
        if x not in new:raise ValueError('Unreviewed native RGB encoder/path')
        new=new.replace(x,y)
    recovered=new
    for x,y in reversed(substitutions):recovered=recovered.replace(y,x)
    if recovered!=old or 'png' in new.lower():raise ValueError('Unexpected RGB producer edit')
    return main[:a]+new+main[b:]


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 with compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_PACKED_ARM_CRC_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit frozen CRC/input base required')
    before=dict(old['products_sha256'])
    for p in (base/'source').iterdir():
        if p.is_file():before[str(p)]=digest(p)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained base products changed')
    header=(base/'source/DenseFrameTelemetry.h').read_text();entry=(base/'source/mono_kv260_network.cc').read_text()
    header,entry=preview_transform(header,entry);entry=color_cache_transform(entry)
    output.mkdir(parents=True,exist_ok=False)
    for n in ('source','bin','codec_cases'):(output/n).mkdir()
    for p in (base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/DenseFrameTelemetry.h').write_text(header);(output/'source/mono_kv260_network.cc').write_text(entry)
    authored=Path(__file__).parent
    (output/'source/check_bmp_preview.cc').write_bytes((authored/'check_bmp_preview.cc').read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=[common[0],'-I'+str(output/'source'),'-include',str(output/'source/Orb60Protocol.h'),*common[1:]]
    link=list(old['link_commands']['executable']);slots=[i for i,x in enumerate(link) if x.endswith('/network.o')]
    if len(slots)!=1:raise ValueError('Unreviewed private main object link')
    def main_link(obj,exe):
        result=list(link);result[slots[0]]=str(obj);result[result.index('-o')+1]=str(exe);return result
    main=output/'network.o';codec=output/'codec.o';exe=output/'bin/mono_kv260_network';unit=output/'bin/check_bmp_preview'
    commands=[[*common,'-c',str(output/'source/check_bmp_preview.cc'),'-o',str(codec)],main_link(codec,unit),
              [*common,'-c',str(output/'source/mono_kv260_network.cc'),'-o',str(main)],main_link(main,exe)]
    state=dict(status='RUNNING',scope='PS RGB encoding/storage only: lossless BMP keyframe cache and owned tmpfs BMP preview. Unchanged packed pixels, CRC, PL, DPU and entire SLAM library; component status is not whole-system acceptance',
               protected_sha256=before,commands=commands,preview_codec='bmp',preview_transport='ram_bmp',rgb_cache_codec='bmp',
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},link_commands=dict(executable=commands[-1]))
    try:
        with (output/'build.log').open('w') as log:
            for i,command in enumerate(commands):
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own compile stopped below256MiB available')
                        time.sleep(.25)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
                if i==1:
                    proof=json.loads(subprocess.check_output([str(unit),str(output/'codec_cases')],text=True));state['codec_gate']=proof
                    if proof['status']!='NATIVE_BMP_LOSSLESS_CODEC_PASS' or proof['cases']!=20:raise ValueError('Native lossless RGB gate failed')
        libs=[Path(p) for p in old['products_sha256'] if Path(p).name=='libORB_SLAM3.so']
        if len(libs)!=1:raise ValueError('Ambiguous retained SLAM library')
        lib=libs[0];deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Native dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/product modified')
        state.update(status='NATIVE_PACKED_BMP_COMPONENT_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (exe,lib,unit)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],codec=state['codec_gate'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','output'):p.add_argument('--'+k,type=Path,required=True)
    run(**vars(p.parse_args()))
