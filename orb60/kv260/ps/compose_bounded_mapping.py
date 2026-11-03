"""PS bounded local BA with publication handoff, exact physical packed frontend.

Local BA optimizes the current keyframe plus at most ten covisible neighbors.
Fixed observing cameras, residuals, solver iterations and outlier tests remain
unchanged. Tracking waits for new map points, while fusion/BA remains concurrent.
This is an algorithm/scheduling candidate, not same-condition speedup evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest
from .compose_local_ba import strongs, local_symbol
from .compile_local_ba_cross import extract
from .compose_packed_mapper import transform as idle_transform
from .build_pose_variant import available

BUILD_STATUS='NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS'


def transform(entry):
    value=idle_transform(entry)
    changes=[('#include "System.h"','#include "System.h"\n#include "KvMapperProgress.h"'),
             ('slam.WaitForLocalMapping(10000)','KvMapperProgress::wait(10000)'),
             ('(mapper_barrier?"idle":"none")','(mapper_barrier?"published":"none")')]
    for old,new in changes:
        if value.count(old)!=1:raise ValueError('Unreviewed publication entry boundary: '+old)
        value=value.replace(old,new)
    return value


def run(root,adapter,base,source_base,mapper,local_ba,output):
    root,adapter,base,source_base,mapper,local_ba,output=map(lambda p:Path(p).resolve(),
        (root,adapter,base,source_base,mapper,local_ba,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 with compile margin required')
    load=lambda p:json.loads((p/'BUILD.json').read_text())
    old,flags,src,sync,ba=map(load,(base,adapter,source_base,mapper,local_ba))
    if (old['status']!='NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS' or
        flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS' or
        src['status']!='NATIVE_PACKED_BMP_COMPONENT_PASS' or
        sync['status']!='NATIVE_MAPPER_PUBLICATION_CANDIDATE_PASS' or
        ba['status']!='NATIVE_LOCAL_BA_COMPOSITION_PASS' or ba['neighbors']!=10):
        raise ValueError('Explicit retained packed/publication/BA10 builds required')
    cp=ba['cross'];source=root/'slam/src/Optimizer.cc'
    private,body=extract(source.read_bytes().decode('utf-8'),10)
    if digest(source)!=cp['source_sha256'] or hashlib.sha256(body.encode()).hexdigest()!=cp['function_sha256']:
        raise ValueError('Original local BA differs from bounded candidate')
    balink=ba['commands'][-2]
    select=lambda values,tail:[Path(x) for x in values if x.endswith(tail)]
    ba_objects=select(balink,'/LocalBundleAdjustment.o');weak_objects=select(balink,'/RetainedOptimizer.o')
    if len(ba_objects)!=1 or len(weak_objects)!=1:raise ValueError('Ambiguous BA object selection')
    baobj,weak=ba_objects[0],weak_objects[0]
    if digest(baobj)!=cp['object_sha256'] or digest(baobj.with_suffix('.cc'))!=cp['private_source_sha256'] or baobj.with_suffix('.cc').read_bytes().decode('utf-8')!=private:
        raise ValueError('Bounded BA source/object differs')
    if not cp['selection_only_change'] or not cp['iterations_and_outlier_thresholds_unchanged'] or not cp['fixed_observing_cameras_retained']:
        raise ValueError('Unreviewed solver/matching changes')
    before={**old['products_sha256'],**sync['products_sha256'],**ba['products_sha256']}
    for folder,manifest in ((source_base,src),(mapper,sync)):
        for name,h in manifest['source_sha256'].items():before[str(folder/'source'/name)]=h
    mapper_obj,progress_obj=mapper/'LocalMapping.o',mapper/'KvMapperProgress.o'
    for p in (baobj,weak,source,mapper_obj,progress_obj):before[str(p)]=digest(p)
    liblink=list(old['link_commands']['library']);mainlink=list(old['link_commands']['executable'])
    slots=lambda command,tail:[i for i,x in enumerate(command) if x.endswith(tail)]
    m=slots(liblink,'/src/LocalMapping.cc.o');o=slots(liblink,'/RetainedOptimizer.o')
    n=slots(mainlink,'/network.o');l=slots(mainlink,'/libORB_SLAM3.so')
    if any(len(v)!=1 for v in (m,o,n,l)) or mainlink[l[0]]!=str(base/'lib/libORB_SLAM3.so'):
        raise ValueError('Unreviewed packed link composition')
    original=Path(liblink[o[0]])
    symbol,kind=local_symbol(original)
    if kind!='T' or local_symbol(weak)!=(symbol,'W') or local_symbol(baobj)!=(symbol,'T') or strongs(weak)!={**strongs(original),symbol:'W'}:
        raise ValueError('Optimizer differs beyond selected BA strong binding')
    for command in (liblink,mainlink):
        for x in command:
            if x.endswith('.o'):
                p=Path(x);p=p if p.is_absolute() else root/'build'/p;before[str(p)]=digest(p)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained products/source changed')
    output.mkdir(parents=True,exist_ok=False)
    for name in ('source','lib','bin'):(output/name).mkdir()
    for p in (source_base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    for name in ('KvMapperProgress.h','KvMapperProgress.cc','LocalMapping.cc'):
        (output/'source'/name).write_bytes((mapper/'source'/name).read_bytes())
    entry=output/'source/mono_kv260_network.cc';entry.write_text(transform(entry.read_text()))
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=[common[0],'-I'+str(output/'source'),'-include',str(output/'source/Orb60Protocol.h'),*common[1:]]
    obj=output/'network.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink[m[0]]=str(mapper_obj);liblink[o[0]]=str(weak)
    liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(baobj))
    liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(progress_obj))
    liblink[liblink.index('-o')+1]=str(lib)
    mainlink[n[0]]=str(obj);mainlink[l[0]]=str(lib);mainlink[mainlink.index('-o')+1]=str(exe)
    for i,x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):mainlink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands=[[*common,'-c',str(entry),'-o',str(obj)],liblink,mainlink]
    state=dict(status='RUNNING',scope=__doc__,commands=commands,protected_sha256=before,
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},
               link_commands=dict(library=liblink,executable=mainlink),mapper_wait_mode='published',
               local_ba_neighbors=10,max_variable_keyframes=11,original_tracking_and_acceptance_tests_retained=True)
    try:
        with (output/'build.log').open('w') as log:
            for command in commands:subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps or local_symbol(lib)[1]!='T':
            raise ValueError('Native bounded mapping dependency/symbol mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained product changed during composition')
        state.update(status=BUILD_STATUS,dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],neighbors=10,mapper_wait_mode='published')),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('root','adapter','base','source_base','mapper','local_ba','output'):p.add_argument('--'+n.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
