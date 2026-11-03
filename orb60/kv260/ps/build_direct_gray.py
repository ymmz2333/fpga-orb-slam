"""Private paired direct-gray adapter, preserving the selected SLAM math library."""
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


def transform(header,main):
    changes=[
        ('double track_ms=0,fps=0;','double track_ms=0,fps=0;uint32_t input_gray_crc=0,source_bgr_crc=0;'),
        ('cv::Mat gray;if(f.image.channels()==1)gray=f.image;else cv::cvtColor(f.image,gray,cv::COLOR_BGR2GRAY);\n        if(!gray.isContinuous())gray=gray.clone();',''),
        ('<<orb_crc32(gray.data,gray.total())','<<f.input_gray_crc<<",\\\"source_bgr_crc\\\":"<<f.source_bgr_crc'),
        ('const std::vector<cv::KeyPoint>* input_keys=nullptr)', 'const std::vector<cv::KeyPoint>* input_keys=nullptr,const cv::Mat* input_gray=nullptr)'),
        ('f->image=image.clone();', 'check(input_gray&&input_gray->type()==CV_8UC1&&input_gray->isContinuous()&&input_gray->rows==720&&input_gray->cols==960&&image.type()==CV_8UC3&&image.isContinuous(),"Explicit paired direct gray/RGB required");f->input_gray_crc=orb_crc32(input_gray->data,input_gray->total());f->source_bgr_crc=orb_crc32(image.data,image.total()*image.elemSize());f->image=image.clone();')]
    changed=header
    for a,b in changes:
        if changed.count(a)!=1:raise ValueError('Unreviewed paired telemetry boundary: '+a)
        changed=changed.replace(a,b)
    restored=changed
    # Restore the deleted block at its exact original location separately.
    for a,b in reversed(changes):
        if b:restored=restored.replace(b,a)
    restored=restored.replace('        \n        std::ostringstream s;', '        '+changes[1][0]+'\n        std::ostringstream s;')
    if restored!=header:raise ValueError('Unexpected telemetry math/body change')
    a=',&raw.keys);';b=',&raw.keys,&f.gray);'
    marker='\\"native_color_preview\\"';replacement='\\"gray_input\\":\\"pyav_direct_gray\\",'+marker
    if main.count(a)!=1 or main.count(marker)!=1:raise ValueError('Unreviewed main telemetry/report boundary')
    return changed,main.replace(a,b).replace(marker,replacement)


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_EXACT_HOTSPOTS_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Unchanged graph base builds required')
    link=list(old['link_commands']['executable']);slots=[i for i,x in enumerate(link) if x.endswith('/network.o')]
    if len(slots)!=1:raise ValueError('Selected native main object mismatch')
    main_obj=Path(link[slots[0]]);main_source=main_obj.parent/'source/mono_kv260_network.cc'
    nearby=main_source.parent/'DenseFrameTelemetry.h';header=nearby if nearby.exists() else root/'slam/include/DenseFrameTelemetry.h'
    before={**old['products_sha256'],**flags['products_sha256'],str(main_obj):digest(main_obj),str(main_source):digest(main_source),str(header):digest(header)}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/product changed')
    changed,entry=transform(header.read_text(),main_source.read_text())
    output.mkdir(parents=True,exist_ok=False)
    for name in ('source','bin'):(output/name).mkdir()
    for p in main_source.parent.glob('*.h'):(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/DenseFrameTelemetry.h').write_text(changed);(output/'source/mono_kv260_network.cc').write_text(entry)
    (output/'source/Kv260VideoPipeline.h').write_bytes((Path(__file__).parent/'Kv260VideoPipeline.h').read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')];common=[common[0],'-I'+str(output/'source'),*common[1:]]
    obj=output/'network.o';exe=output/'bin/mono_kv260_network';link[slots[0]]=str(obj);link[link.index('-o')+1]=str(exe)
    commands=[[*common,'-c',str(output/'source/mono_kv260_network.cc'),'-o',str(obj)],link]
    state=dict(status='RUNNING',scope='Explicit paired gray/RGB input and metadata only; unchanged SLAM graph/math and default JPEG; board codec/source/full pipeline gates remain required',
               gray_input='pyav_direct_gray',protected_sha256=before,source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,link_commands=dict(executable=link))
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
        library=base/'lib/libORB_SLAM3.so';deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(library) not in deps:raise ValueError('Paired adapter native dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained mapping source/product modified')
        state.update(status='NATIVE_DIRECT_GRAY_COMPONENT_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (exe,library)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','base','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
