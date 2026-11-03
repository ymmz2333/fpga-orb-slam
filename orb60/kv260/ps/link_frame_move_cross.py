"""Verify frozen dependencies and cross ABI on KV260, then link private PS code."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest
from .compose_local_ba import strongs


def run(root,base,library_base,component,cross,output):
    root,base,library_base,component,cross,output=map(lambda p:Path(p).resolve(),(root,base,library_base,component,cross,output))
    if platform.machine()!='aarch64':raise ValueError('Native KV260 linker and runtime required')
    old=json.loads((base/'BUILD.json').read_text());library=json.loads((library_base/'BUILD.json').read_text());proof=json.loads((component/'COMPONENT.json').read_text());cp=json.loads((cross/'CROSS_COMPILE.json').read_text())
    variant=cp.get('variant','frame-move');expected_status={'frame-move':'CROSS_FRAME_OBJECTS_COMPILED_REQUIRES_NATIVE_GATES','defer-strong-motion':'CROSS_MOTION_POLICY_COMPILED_REQUIRES_NATIVE_GATES'}
    if old['status']!='NATIVE_PACKED_BMP_COMPONENT_PASS' or library['status']!='NATIVE_PACKED_ARM_CRC_COMPONENT_PASS' or proof['status']!='EXACT_FRAME_MOVE_COMPONENT_PASS' or cp['status']!=expected_status.get(variant):raise ValueError('Explicit completed component and cross object gates required')
    if variant=='defer-strong-motion':
        from .motion_pose_transform import transform
        if str(cross)!=cp.get('board_output') or (cross/'Tracking.cc').read_text()!=transform((root/'slam/src/Tracking.cc').read_text()) or digest(cross/'Tracking.cc')!=cp['private_tracking_sha256'] or digest(cross/'MotionPosePolicy.h')!=cp['policy_header_sha256'] or digest(Path(__file__).with_name('MotionPosePolicy.h'))!=cp['policy_header_sha256']:raise ValueError('Private motion policy source/header differs from reviewed transform')
    if set(cp['products_sha256'])!={'Tracking.o','FrameCheck.o','FrameABI.o'} or any(digest(cross/n)!=h for n,h in cp['products_sha256'].items()):raise ValueError('Cross products changed')
    manifest=root/'FRAME_CROSS_INPUTS_20261103_A.json'
    if digest(manifest)!=cp['inputs_manifest_sha256']:raise ValueError('Frozen source export differs')
    checked={};builtins=0
    for name,item in cp['dependencies'].items():
        if item.get('toolchain_builtin'):builtins+=1;continue
        p=Path(item['board_path']).resolve()
        if root not in p.parents and Path('/usr/include') not in p.parents:raise ValueError('Unexpected cross dependency path')
        if digest(p)!=item['sha256']:raise ValueError('Captured dependency differs from actual board: '+str(p))
        checked[str(p)]=item['sha256']
    if len(checked)<100:raise ValueError('Insufficient captured dependency coverage')
    before={**old['products_sha256'],**library['products_sha256'],**checked,str(component/'COMPONENT.json'):digest(component/'COMPONENT.json'),str(cross/'CROSS_COMPILE.json'):digest(cross/'CROSS_COMPILE.json')}
    liblink=list(library['link_commands']['library']);mainlink=list(old['link_commands']['executable'])
    slots=[i for i,x in enumerate(liblink) if x.endswith('/src/Tracking.cc.o')];libs=[i for i,x in enumerate(mainlink) if x.endswith('/libORB_SLAM3.so')];mains=[i for i,x in enumerate(mainlink) if x.endswith('/network.o')]
    if len(slots)!=1 or len(libs)!=1 or len(mains)!=1 or mainlink[libs[0]]!=str(library_base/'lib/libORB_SLAM3.so'):raise ValueError('Selected retained link mismatch')
    original=Path(liblink[slots[0]]);original=original if original.is_absolute() else root/'build'/original
    for command in (liblink,mainlink):
        for value in command:
            if value.endswith('.o'):
                p=Path(value);p=p if p.is_absolute() else root/'build'/p;before[str(p)]=digest(p)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained product changed')
    obj=cross/'Tracking.o';old_symbols={s:k for s,k in strongs(original).items() if k=='T'};new_symbols={s:k for s,k in strongs(obj).items() if k=='T'}
    if old_symbols!=new_symbols:raise ValueError('Cross strong Tracking ABI mismatch')
    output.mkdir(parents=True,exist_ok=False)
    for n in ('lib','bin'):(output/n).mkdir()
    lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network';unit=output/'bin/check_frame_cross'
    liblink[slots[0]]=str(obj);liblink[liblink.index('-o')+1]=str(lib)
    mainlink[libs[0]]=str(lib);mainlink[mainlink.index('-o')+1]=str(exe)
    for i,x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):mainlink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    unitlink=list(mainlink);unitlink[mains[0]:mains[0]+1]=[str(cross/'FrameCheck.o'),str(cross/'FrameABI.o')];unitlink[unitlink.index('-o')+1]=str(unit)
    commands=[liblink,mainlink,unitlink]
    state=dict(status='RUNNING',scope='PC-compiled unchanged Tracking body, same exact Frame storage transfer, actual-board header check and semantic/ABI replay. Full pixel and actual DPU/Mali system gates remain required.',
               protected_sha256=before,cross_objects_sha256=cp['products_sha256'],checked_board_dependencies=len(checked),toolchain_builtin_dependencies=builtins,tracking_strong_symbols=len(new_symbols),commands=commands,link_commands=dict(library=liblink,executable=mainlink))
    if variant=='defer-strong-motion':state.update(scope='Private PS algorithm candidate: defer preliminary strong mono motion solves, retain final local-map pose and original acceptance gates. Frame semantic replay is not whole tracking/quality/performance acceptance.',variant=variant,policy_header_sha256=cp['policy_header_sha256'],private_tracking_sha256=cp['private_tracking_sha256'])
    try:
        with (output/'link.log').open('w') as log:
            for command in commands:subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        semantic=output/'cross_frame_semantics.bin';r=json.loads(subprocess.check_output([str(unit),str(semantic),'0'],text=True))
        expected={row['sha256'] for row in proof['runs']}
        if r['status']!='FRAME_ASSIGNMENT_FIXTURE_RECORDED' or r['cases']!=128 or r['storage_transfer_checks']!=128 or expected!={digest(semantic)}:raise ValueError('Cross/native layout, field or ownership mismatch')
        state['native_cross_semantic']=dict(report=r,sha256=digest(semantic),matches_all_original_reference_runs=True)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Private native cross link mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained dependency changed')
        state.update(status='NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS' if variant=='frame-move' else 'NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe,unit)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],checked_board_dependencies=len(checked),native_semantic_cases=r['cases'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','base','library_base','component','cross','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
