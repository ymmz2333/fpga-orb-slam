"""Bounded monocular keyframe handoff; preserve geometry gates and drain at end."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import available
from .compose_local_ba import strongs

SYMBOL='_ZN9ORB_SLAM38Tracking15NeedNewKeyFrameEv'


def extract(source):
    first='bool Tracking::NeedNewKeyFrame()';last='void Tracking::CreateNewKeyFrame()'
    if source.count(first)!=1 or source.count(last)!=1:raise ValueError('Unreviewed keyframe selection boundary')
    body=source[source.index(first):source.index(last,source.index(first))].rstrip()
    old_ready='bool bLocalMappingIdle = mpLocalMapper->AcceptKeyFrames();'
    new_ready=old_ready+'\n    const bool bMonoSlot = mSensor==System::MONOCULAR && mpLocalMapper->KeyframesInQueue()<1;'
    old_gate='(mCurrentFrame.mnId>=mnLastKeyFrameId+mMinFrames) && bLocalMappingIdle'
    new_gate='(mCurrentFrame.mnId>=mnLastKeyFrameId+mMinFrames) && (bLocalMappingIdle || bMonoSlot)'
    old_return='//std::cout << "NeedNewKeyFrame: localmap is busy" << std::endl;\n                return false;'
    new_return='//std::cout << "NeedNewKeyFrame: localmap is busy" << std::endl;\n                return bMonoSlot;'
    changed=body
    for old,new in ((old_ready,new_ready),(old_gate,new_gate),(old_return,new_return)):
        if changed.count(old)!=1:raise ValueError('Unreviewed monocular busy/idle policy')
        changed=changed.replace(old,new)
    restored=changed
    for old,new in ((old_return,new_return),(old_gate,new_gate),(old_ready,new_ready)):restored=restored.replace(new,old)
    if restored!=body:raise ValueError('Unexpected tracking condition change')
    prefix=source[:source.index('#include')]
    prefix+=''.join('#include "%s"\n'%h for h in ('Tracking.h','System.h','LocalMapping.h','Atlas.h','KeyFrame.h'))
    return prefix+'using namespace std;\nnamespace ORB_SLAM3 {\n'+changed+'\n}\n',body


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_EXACT_HOTSPOTS_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit unchanged-graph base builds required')
    source=root/'slam/src/Tracking.cc';original=root/'build/CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o'
    private,body=extract(source.read_text());original_symbols=strongs(original)
    if original_symbols.get(SYMBOL)!='T':raise ValueError('Original tracking method binding mismatch')
    relocs=subprocess.check_output(['readelf','-rW',str(original)],text=True)
    if sum('R_AARCH64_CALL26' in x and SYMBOL in x for x in relocs.splitlines())!=1:raise ValueError('Retained tracker call must not bypass candidate')
    liblink=list(old['link_commands']['library']);exelink=list(old['link_commands']['executable'])
    mains=[i for i,x in enumerate(exelink) if x.endswith('/network.o')]
    if len(mains)!=1:raise ValueError('Native main object mismatch')
    main_source=Path(exelink[mains[0]]).parent/'source/mono_kv260_network.cc'
    system=root/'slam/src/System.cc';header=root/'slam/include/System.h';system_obj=root/'build/CMakeFiles/ORB_SLAM3.dir/src/System.cc.o'
    before={**old['products_sha256'],**flags['products_sha256'],**{str(p):digest(p) for p in (source,original,system,header,system_obj,main_source)}}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source or product changed')
    text=header.read_text();anchor='private:\n\n    void SaveAtlas'
    if text.count(anchor)!=1:raise ValueError('Unreviewed public System API boundary')
    text=text.replace(anchor,'double WaitForLocalMapping(unsigned timeout_ms);\n\n'+anchor)
    entry=main_source.read_text();shutdown='slam.Shutdown();slam.ExportBridgeMap'
    if entry.count(shutdown)!=1:raise ValueError('Unreviewed final mapping drain boundary')
    entry=entry.replace(shutdown,'double final_mapper_ms=slam.WaitForLocalMapping(10000);atomic_json(out+"/mapper_drain.json","{\\\"milliseconds\\\":"+std::to_string(final_mapper_ms)+"}");'+shutdown)
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','lib','bin'):(output/folder).mkdir()
    for p in main_source.parent.glob('*.h'):(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/NeedNewKeyFrame.cc').write_text(private);(output/'source/System.h').write_text(text)
    (output/'source/System.cc').write_bytes(system.read_bytes()+b'\n#include "MapperBarrier.inc"\n')
    (output/'source/MapperBarrier.inc').write_bytes((Path(__file__).parent/'MapperBarrier.inc').read_bytes())
    (output/'source/mono_kv260_network.cc').write_text(entry)
    common=list(flags['commands'][0]);common=common[:common.index('-c')];common=[common[0],'-I'+str(output/'source'),*common[1:],'-fvisibility-inlines-hidden']
    need=output/'NeedNewKeyFrame.o';weak=output/'RetainedTracking.o';sysobj=output/'System.o';main=output/'network.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    commands=[[*common,'-c',str(output/'source/NeedNewKeyFrame.cc'),'-o',str(need)],
              ['objcopy','--weaken-symbol='+SYMBOL,str(original),str(weak)],
              [*common,'-c',str(output/'source/System.cc'),'-o',str(sysobj)],
              [*common,'-c',str(output/'source/mono_kv260_network.cc'),'-o',str(main)]]
    for old_slot,new_obj in [('CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o',weak),('CMakeFiles/ORB_SLAM3.dir/src/System.cc.o',sysobj)]:
        if liblink.count(old_slot)!=1:raise ValueError('Original object library link mismatch')
        liblink[liblink.index(old_slot)]=str(new_obj)
    liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(need));liblink[liblink.index('-o')+1]=str(lib)
    oldlib=str(base/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Selected main library link mismatch')
    exelink[exelink.index(oldlib)]=str(lib);exelink[mains[0]]=str(main);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands.extend([liblink,exelink])
    state=dict(status='RUNNING',scope='Changed monocular scheduling only: at most1pending keyframe when busy, final queue drain included in whole geometry; quality/performance gates remain required',
               pending_capacity=1,initialization_queue_unchanged=True,geometry_and_inlier_thresholds_unchanged=True,
               source_function_sha256=hashlib.sha256(body.encode()).hexdigest(),protected_sha256=before,
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,link_commands=dict(library=liblink,executable=exelink))
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:
                child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    while child.poll() is None:
                        if available()<256*1024:
                            os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own native compile stopped below256MiB available')
                        time.sleep(.5)
                    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
                finally:
                    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
        if strongs(weak)!={**original_symbols,SYMBOL:'W'} or strongs(lib).get(SYMBOL)!='T':raise ValueError('Unexpected retained tracker binding change')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Native bounded queue dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/product modified')
        state.update(status='NATIVE_MONO_QUEUE_CANDIDATE_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (exe,lib)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('root','adapter','base','output'):p.add_argument('--'+key,type=Path,required=True)
    run(**vars(p.parse_args()))
