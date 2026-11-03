"""Private lossless preview producer; preserve the selected PS mapping library."""
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
    old=r'cv::imencode(".jpg",f.image,jpeg,{cv::IMWRITE_JPEG_QUALITY,80}),"JPEG encode"'
    new=r'cv::imencode(".bmp",f.image,jpeg),"BMP encode"'
    meta=r'<<",\"source_gray\":"'
    marked=r'<<",\"image_codec\":\"bmp\",\"source_gray\":"'
    # The source contains C++ string escapes, not JSON-decoded strings.
    meta=meta.replace('\\\\','\\');marked=marked.replace('\\\\','\\')
    if header.count(old)!=1 or header.count(meta)!=1:raise ValueError('Unreviewed preview encoder or metadata boundary')
    changed=header.replace(old,new).replace(meta,marked)
    if changed.replace(new,old).replace(marked,meta)!=header:raise ValueError('Unexpected telemetry body change')
    call='new DenseFrameTelemetry(out+"/tracking/telemetry",false)'
    replacement='new DenseFrameTelemetry(kv_lossless_preview_folder(),false)'
    anchor='namespace {\n'
    helper='std::string kv_lossless_preview_folder(){const char* p=std::getenv("ORB60_TELEMETRY_DIR");if(!p||p[0]!=\'/\')throw std::runtime_error("Owned absolute RAM preview path required");return p;}\n'
    if main.count(call)!=1 or main.count(anchor)!=1:raise ValueError('Unreviewed native preview constructor')
    entry=main.replace(call,replacement).replace(anchor,anchor+helper)
    if entry.replace(anchor+helper,anchor).replace(replacement,call)!=main:raise ValueError('Unexpected native mapping body change')
    return changed,entry


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_EXACT_HOTSPOTS_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit native base builds required')
    link=list(old['link_commands']['executable']);mains=[i for i,x in enumerate(link) if x.endswith('/network.o')]
    if len(mains)!=1:raise ValueError('Selected native main object mismatch')
    main_obj=Path(link[mains[0]]);main_source=main_obj.parent/'source/mono_kv260_network.cc'
    nearby=main_source.parent/'DenseFrameTelemetry.h';header=nearby if nearby.exists() else root/'slam/include/DenseFrameTelemetry.h'
    before={**old['products_sha256'],**flags['products_sha256'],str(main_obj):digest(main_obj),str(main_source):digest(main_source),str(header):digest(header)}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained mapping build/source changed')
    changed,entry=transform(header.read_text(),main_source.read_text())
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','bin','codec_cases'):(output/folder).mkdir()
    for p in main_source.parent.glob('*.h'):(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/DenseFrameTelemetry.h').write_text(changed);(output/'source/mono_kv260_network.cc').write_text(entry)
    (output/'source/check_bmp_preview.cc').write_bytes((Path(__file__).parent/'check_bmp_preview.cc').read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')];common=[common[0],'-I'+str(output/'source'),*common[1:]]
    network=output/'network.o';codec=output/'codec.o';exe=output/'bin/mono_kv260_network';check=output/'bin/check_bmp_preview'
    def make_link(obj,target):
        command=list(link);command[mains[0]]=str(obj);command[command.index('-o')+1]=str(target);return command
    commands=[[*common,'-c',str(output/'source/check_bmp_preview.cc'),'-o',str(codec)],make_link(codec,check),
              [*common,'-c',str(output/'source/mono_kv260_network.cc'),'-o',str(network)],make_link(network,exe)]
    state=dict(status='RUNNING',scope='Private PS lossless preview and RAM directory hook only; mapping library unchanged, full board gates remain required',
               preview_codec='bmp',preview_transport='ram_bmp',protected_sha256=before,
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,
               link_commands=dict(executable=commands[-1]))
    try:
        with (output/'build.log').open('w') as log:
            for i,command in enumerate(commands):
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own compile stopped below256MiB available')
                        time.sleep(.5)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
                if i==1:
                    proof=json.loads(subprocess.check_output([str(check),str(output/'codec_cases')],text=True));state['codec_gate']=proof
                    if proof['status']!='NATIVE_BMP_LOSSLESS_CODEC_PASS' or proof['cases']!=20:raise ValueError('Lossless codec gate failed')
        library=base/'lib/libORB_SLAM3.so';deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(library) not in deps:raise ValueError('Native lossless preview dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained mapping/source modified')
        state.update(status='NATIVE_RAM_BMP_PREVIEW_COMPONENT_PASS',dependencies=deps,
                     products_sha256={str(p):digest(p) for p in (exe,library,check)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','base','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
