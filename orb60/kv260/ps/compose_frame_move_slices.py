"""Bounded compilation of unchanged mono tracking methods with Frame moves."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import available
from .check_frame_move import transform
from .compose_local_ba import strongs

METHODS=('GrabImageMonocular','Track','MonocularInitialization','CreateInitialMapMonocular')


def extract(source,name):
    matches=list(re.finditer(r'^[^\n]+Tracking::'+re.escape(name)+r'\([^\n]*',source,re.M))
    if len(matches)!=1:raise ValueError('One reviewed tracking method required: '+name)
    start=matches[0].start();opening=source.index('{',start);i=opening;depth=0;state='code'
    while i<len(source):
        c=source[i];n=source[i:i+2]
        if state=='line':
            if c=='\n':state='code'
        elif state=='block':
            if n=='*/':state='code';i+=1
        elif state in ('"',"'"):
            if c=='\\':i+=1
            elif c==state:state='code'
        elif n=='//':state='line';i+=1
        elif n=='/*':state='block';i+=1
        elif c in ('"',"'"):state=c
        elif c=='{':depth+=1
        elif c=='}':
            depth-=1
            if depth==0:
                body=source[start:i+1]
                prefix=source[:source.index('namespace ORB_SLAM3')]
                for impl,decl in [('Kv260DepthKeyframesImpl.h','Kv260DepthKeyframes.h'),('BridgeTrackingDiagnosticsImpl.h','BridgeTrackingDiagnostics.h')]:
                    old='#include "'+impl+'"'
                    if prefix.count(old)!=1:raise ValueError('Unreviewed shared state implementation boundary')
                    prefix=prefix.replace(old,'#include "'+decl+'"')
                # Definitions/TLS stay in the retained original Tracking object.
                prefix+='#include "KeyFrame.h"\n#include <cmath>\n#include <iomanip>\n'
                return prefix+'namespace ORB_SLAM3 {\n'+body+'\n}\n',body
        i+=1
    raise ValueError('Unclosed tracking method')


def run(root,adapter,base,library_base,component,output):
    root,adapter,base,library_base,component,output=map(lambda p:Path(p).resolve(),(root,adapter,base,library_base,component,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and compile margin required')
    old=json.loads((base/'BUILD.json').read_text());library=json.loads((library_base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text());proof=json.loads((component/'COMPONENT.json').read_text())
    if old['status']!='NATIVE_PACKED_BMP_COMPONENT_PASS' or library['status']!='NATIVE_PACKED_ARM_CRC_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit retained bases required')
    if proof['status']!='EXACT_FRAME_MOVE_COMPONENT_PASS' or not proof['beneficial_microbenchmark']:raise ValueError('Exact native ownership/component gate required')
    for row in proof['runs']:
        if digest(component/row['file'])!=row['sha256']:raise ValueError('Component field output changed')
    header=root/'slam/include/Frame.h';tracking=root/'slam/src/Tracking.cc';changed=transform(header.read_text());source=tracking.read_bytes().decode()
    if digest(tracking)!='38e4fb1594c7d4f6e4fa2676ad4c3c508221b1daaee41cbe6d287257e073c7ae' or changed!=(component/'candidate/Frame.h').read_text() or digest(component/'candidate/Frame.h')!=proof['header_sha256']:raise ValueError('Unreviewed retained Frame/Tracking source')
    liblink=list(library['link_commands']['library']);mainlink=list(old['link_commands']['executable'])
    slots=[i for i,x in enumerate(liblink) if x.endswith('/src/Tracking.cc.o')];libslots=[i for i,x in enumerate(mainlink) if x.endswith('/libORB_SLAM3.so')]
    if len(slots)!=1 or len(libslots)!=1 or mainlink[libslots[0]]!=str(library_base/'lib/libORB_SLAM3.so'):raise ValueError('Ambiguous selected link')
    original=Path(liblink[slots[0]]);original=original if original.is_absolute() else root/'build'/original
    old_symbols=strongs(original);selected={}
    strong_names=[s for s,k in old_symbols.items() if k=='T']
    demangled=subprocess.check_output(['c++filt'],input='\n'.join(strong_names)+'\n',text=True).splitlines()
    if len(demangled)!=len(strong_names):raise ValueError('Tracking ABI demangler output mismatch')
    for method in METHODS:
        found=[s for s,name in zip(strong_names,demangled) if 'ORB_SLAM3::Tracking::'+method+'(' in name]
        if len(found)!=1:raise ValueError('One retained strong method ABI required: '+method)
        selected[method]=found[0]
    before={**old['products_sha256'],**library['products_sha256'],**proof['products_sha256'],str(header):digest(header),str(tracking):digest(tracking),str(component/'COMPONENT.json'):digest(component/'COMPONENT.json')}
    for command in (liblink,mainlink):
        for value in command:
            if value.endswith('.o'):
                path=Path(value);path=path if path.is_absolute() else root/'build'/path
                before[str(path)]=digest(path)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/object changed')
    output.mkdir(parents=True,exist_ok=False)
    for n in ('source','lib','bin'):(output/n).mkdir()
    for p in (base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    (output/'source/Frame.h').write_text(changed)
    sources={};bodies={}
    for name in METHODS:
        text,body=extract(source,name);p=output/'source'/(name+'.cc');p.write_text(text);sources[name]=p;bodies[name]=hashlib.sha256(body.encode()).hexdigest()
    common=list(flags['commands'][0]);common=common[:common.index('-c')];common=[common[0],'-I'+str(output/'source'),'-include',str(output/'source/Frame.h'),*common[1:]]
    objects={name:output/(name+'.o') for name in METHODS};retained=output/'RetainedTracking.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink[slots[0]]=str(retained);liblink[slots[0]:slots[0]]=list(map(str,objects.values()));liblink[liblink.index('-o')+1]=str(lib)
    mainlink[libslots[0]]=str(lib);mainlink[mainlink.index('-o')+1]=str(exe)
    for i,x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):mainlink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands=[];state=dict(status='RUNNING',scope='Four unchanged mono tracking method bodies compiled separately with exact Frame storage transfer. All other methods, shared depth/diagnostic state and math objects retained. Component only, not system acceptance.',
                           protected_sha256=before,component_proof_sha256=digest(component/'COMPONENT.json'),method_body_sha256=bodies,selected_strong_symbols=selected,
                           source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,link_commands=dict(library=liblink,executable=mainlink))
    def invoke(command):
        commands.append(command);child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while child.poll() is None:
                if available()<256*1024:
                    os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own bounded compile stopped below256MiB available')
                time.sleep(.5)
            if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        finally:
            if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
    try:
        with (output/'build.log').open('w') as log:
            for name in METHODS:
                invoke([*common,'-c',str(sources[name]),'-o',str(objects[name])])
                if {s for s,k in strongs(objects[name]).items() if k=='T'}!={selected[name]}:raise ValueError('Unexpected strong symbol in method slice')
            invoke(['objcopy',*['--weaken-symbol='+s for s in selected.values()],str(original),str(retained)])
            if strongs(retained)!={**old_symbols,**{s:'W' for s in selected.values()}}:raise ValueError('Unexpected retained Tracking symbol change')
            invoke(liblink);invoke(mainlink)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Bounded native dependency mismatch')
        if any(strongs(lib).get(s)!='T' for s in selected.values()):raise ValueError('Selected tracking methods not strongly bound')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/object modified')
        state.update(status='NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],methods=list(METHODS))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','library_base','component','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
