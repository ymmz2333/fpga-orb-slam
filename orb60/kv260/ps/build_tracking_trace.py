"""Private PS observation hooks; retain all geometry and Frame code unchanged."""
import argparse,json,os,platform,signal,subprocess,time
from pathlib import Path
from .build_network_adapter import digest
from .build_pose_variant import available
from .compose_local_ba import strongs
from ..tracking_trace import BUILD_STATUS


def transform(header,entry):
    include='#include <cstdint>'
    hook='    r.records_crc=orb_crc32(payload.data()+128,count*64);'
    start='    FeatureIO::Configure("fpga-pipeline",argv[5]);'
    state='            const int state=slam.GetTrackingState();const bool ok=state==2&&pose.matrix().allFinite();valid+=ok;'
    finish='    journal.close();source.close();'
    for text,anchor in ((header,include),(header,hook),(entry,start),(entry,state),(entry,finish)):
        if text.count(anchor)!=1:raise ValueError('Unreviewed observation boundary')
    additions=[(include,include+'\n#include "BridgeTrackingDiagnostics.h"\n#include <cstdlib>\n#include <string>'),
               (hook,hook+'''\n    static thread_local uint64_t trace_frame=0;
    static const bool trace_enabled=std::getenv("ORB60_TRACKING_TRACE")&&std::string(std::getenv("ORB60_TRACKING_TRACE"))=="1";
    if(trace_enabled)ORB_SLAM3::BridgeDiag::begin(trace_frame++,stamp,count,payload.data()+128);''')]
    h=header
    for old,new in additions:h=h.replace(old,new)
    changes=[(start,'''    std::unique_ptr<BridgeDiag::Writer> tracking_trace;
    if(std::getenv("ORB60_TRACKING_TRACE")&&std::string(std::getenv("ORB60_TRACKING_TRACE"))=="1")
        tracking_trace.reset(new BridgeDiag::Writer(out+"/tracking"));
'''+start),(state,state+'''
            if(tracking_trace){double tcw[12];for(unsigned r=0;r<3;++r)for(unsigned c=0;c<4;++c)tcw[r*4+c]=pose.matrix()(r,c);
                tracking_trace->write(state,ok?tcw:nullptr);}'''),
             (finish,'    if(tracking_trace)tracking_trace->finish();\n'+finish)]
    e=entry
    for old,new in changes:e=e.replace(old,new)
    rh,re=h,e
    for old,new in reversed(additions):rh=rh.replace(new,old)
    for old,new in reversed(changes):re=re.replace(new,old)
    if rh!=header or re!=entry:raise ValueError('Observation changed original code')
    return h,e


def run(root,adapter,base,source_base,output):
    root,adapter,base,source_base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,source_base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native board with compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());src=json.loads((source_base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS' or src['status']!='NATIVE_PACKED_BMP_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit unchanged retained bases required')
    liblink=list(old['link_commands']['library']);mainlink=list(old['link_commands']['executable'])
    slots=[i for i,x in enumerate(liblink) if x.endswith('/FeatureIO.o')];mains=[i for i,x in enumerate(mainlink) if x.endswith('/network.o')];libs=[i for i,x in enumerate(mainlink) if x.endswith('/libORB_SLAM3.so')]
    if len(slots)!=1 or len(mains)!=1 or len(libs)!=1 or mainlink[libs[0]]!=str(base/'lib/libORB_SLAM3.so'):raise ValueError('Unreviewed selected link')
    before={**old['products_sha256'],str(base/'BUILD.json'):digest(base/'BUILD.json')}
    for cmd in (liblink,mainlink):
        for value in cmd:
            if value.endswith('.o'):
                p=Path(value);p=p if p.is_absolute() else root/'build'/p;before[str(p)]=digest(p)
    for p in (source_base/'source').iterdir():
        if p.is_file():before[str(p)]=digest(p)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained base changed')
    record=adapter/'source/Kv260NetworkRecord.h'
    if digest(record)!=flags['source_sha256']['Kv260NetworkRecord.h']:raise ValueError('Frozen adapter observation header changed')
    before[str(record)]=digest(record)
    header,entry=transform(record.read_text(),(source_base/'source/mono_kv260_network.cc').read_text())
    output.mkdir(parents=True,exist_ok=False)
    for name in ('source','lib','bin'):(output/name).mkdir()
    for p in (source_base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/Kv260NetworkRecord.h').write_text(header);(output/'source/mono_kv260_network.cc').write_text(entry)
    feature=output/'FeatureIO.o';main=output/'network.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    original=Path(liblink[slots[0]]);liblink[slots[0]]=str(feature);liblink[liblink.index('-o')+1]=str(lib)
    mainlink[mains[0]]=str(main);mainlink[libs[0]]=str(lib);mainlink[mainlink.index('-o')+1]=str(exe)
    for i,x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):mainlink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=[common[0],'-I'+str(output/'source'),'-include',str(output/'source/Orb60Protocol.h'),*common[1:]]
    commands=[[*common,'-c',str(output/'source/FeatureIO.cc'),'-o',str(feature)],liblink,[*common,'-c',str(output/'source/mono_kv260_network.cc'),'-o',str(main)],mainlink]
    state=dict(status='RUNNING',scope='Observation only, unchanged geometry/Tracking/Frame; profile=true system run required. Not an acceleration or hardware gate.',protected_sha256=before,commands=commands,link_commands=dict(library=liblink,executable=mainlink),source_sha256={p.name:digest(p) for p in (output/'source').iterdir()})
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own diagnostic compile stopped below256MiB available')
                        time.sleep(.25)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
        if {s:k for s,k in strongs(original).items() if k=='T'}!={s:k for s,k in strongs(feature).items() if k=='T'}:raise ValueError('Feature observation changed strong ABI')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Private diagnostic runtime dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained products changed')
        state.update(status=BUILD_STATUS,dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','source_base','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
