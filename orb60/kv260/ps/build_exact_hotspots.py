"""Native exact-result PS optimizations selected from actual CPU samples."""
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


def extract_grid(source):
    first='vector<size_t> Frame::GetFeaturesInArea('
    following='bool Frame::PosInGrid('
    if source.count(first)!=1 or source.count(following)!=1:raise ValueError('Unreviewed frame grid boundary')
    original=source[source.index(first):source.index(following,source.index(first))].rstrip()
    substitutions=[('const vector<size_t> vCell =','const vector<size_t>& vCell ='),
                   ('vIndices.reserve(N);','vIndices.reserve(std::min(N,64));')]
    changed=original
    for old,new in substitutions:
        if changed.count(old)!=1:raise ValueError('Unreviewed grid storage operation')
        changed=changed.replace(old,new)
    recovered=changed
    for old,new in reversed(substitutions):recovered=recovered.replace(new,old)
    if recovered!=original:raise ValueError('Grid math or iteration order changed')
    license=source[:source.index('#include')]
    prefix=license+'#include "Frame.h"\n#include <algorithm>\n#include <cmath>\nusing namespace std;\n'
    production=prefix+'namespace ORB_SLAM3 {\n'+changed+'\n}\n'
    args='const ORB_SLAM3::Frame& self, const float &x, const float &y, const float &r, const int minLevel, const int maxLevel, const bool bRight'
    body=changed[changed.index('{')+1:]
    aliases='\nconst auto& mGrid=self.mGrid;const auto& mGridRight=self.mGridRight;\nconst auto& mvKeysUn=self.mvKeysUn;const auto& mvKeys=self.mvKeys;const auto& mvKeysRight=self.mvKeysRight;\nconst int N=self.N,Nleft=self.Nleft;\nconst float mnMinX=ORB_SLAM3::Frame::mnMinX,mnMinY=ORB_SLAM3::Frame::mnMinY,mfGridElementWidthInv=ORB_SLAM3::Frame::mfGridElementWidthInv,mfGridElementHeightInv=ORB_SLAM3::Frame::mfGridElementHeightInv;\n'
    test=prefix+'vector<size_t> kv_grid_candidate('+args+') {\n'+aliases+body+'\n'
    return production,test,original


def run(root,adapter,base,fixture,output):
    root,adapter,base,fixture,output=map(lambda p:Path(p).resolve(),(root,adapter,base,fixture,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 and compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_NEON_DISTANCE_CANDIDATE_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit unchanged-graph PS builds required')
    source=root/'slam/src/Frame.cc';original=root/'build/CMakeFiles/ORB_SLAM3.dir/src/Frame.cc.o'
    dbow=root/'slam/Thirdparty/DBoW2/lib/libDBoW2.so'
    before={**old['products_sha256'],**flags['products_sha256'],str(source):digest(source),str(original):digest(original),str(dbow):digest(dbow)}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source/products changed')
    fixture_proof=json.loads(fixture.with_suffix('.json').read_text())
    if fixture_proof['cases']!=10000 or fixture_proof['sha256']!=digest(fixture):raise ValueError('Independent bit-count fixture mismatch')
    production,test,body=extract_grid(source.read_bytes().decode())
    symbols=strongs(original);names=[s for s in symbols if 'GetFeaturesInArea' in s]
    if len(names)!=1 or symbols[names[0]]!='T':raise ValueError('Unreviewed grid method binding')
    symbol=names[0]
    relocs=subprocess.check_output(['readelf','-rW',str(root/'build/CMakeFiles/ORB_SLAM3.dir/src/ORBmatcher.cc.o')],text=True)
    calls=[s for s in relocs.splitlines() if 'R_AARCH64_CALL26' in s and symbol in s]
    if not calls:raise ValueError('No retained external grid method calls')
    output.mkdir(parents=True,exist_ok=False)
    for name in ('source','lib','bin'):(output/name).mkdir()
    (output/'source/FrameGrid.cc').write_text(production);(output/'source/GridFixture.cc').write_text(test)
    authored=Path(__file__).parent
    for name in ('Hamming256Neon.h','BowDistanceNeon.h','BowDistanceNeon.cc','check_bow_neon.cc','check_grid_area.cc'):
        (output/'source'/name).write_bytes((authored/name).read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=[common[0],'-I'+str(output/'source'),*common[1:],'-mcpu=cortex-a53','-fvisibility-inlines-hidden']
    weak=output/'RetainedFrame.o';grid=output/'FrameGrid.o';bow=output/'BowDistanceNeon.o';grid_fixture=output/'GridFixture.o'
    lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network'
    liblink=list(old['commands'][-2]);slot='CMakeFiles/ORB_SLAM3.dir/src/Frame.cc.o'
    if liblink.count(slot)!=1:raise ValueError('Retained frame library link mismatch')
    liblink[liblink.index(slot)]=str(weak);i=next(i for i,x in enumerate(liblink) if x.endswith('.o'));liblink[i:i]=[str(grid),str(bow)];liblink[liblink.index('-o')+1]=str(lib)
    original_exelink=list(old['commands'][-1]);oldlib=str(base/'lib/libORB_SLAM3.so')
    def link_main(main_objects,target,selected):
        command=list(original_exelink);mains=[i for i,x in enumerate(command) if x.endswith('/network.o')]
        if len(mains)!=1 or command.count(oldlib)!=1:raise ValueError('Selected main/library link mismatch')
        command[command.index(oldlib)]=str(selected);command[command.index('-o')+1]=str(target)
        for i,x in enumerate(command):
            if x.startswith('-Wl,-rpath,'):command[i]='-Wl,-rpath,'+str(selected.parent)+':'+x.removeprefix('-Wl,-rpath,')
        command[mains[0]:mains[0]+1]=[str(x) for x in main_objects]
        if '-ldl' not in command:command.append('-ldl')
        return command
    main_obj=next(Path(x) for x in original_exelink if x.endswith('/network.o'))
    exelink=link_main([main_obj],exe,lib)
    commands=[]
    state=dict(status='RUNNING',scope='PS exact index/order and integer distance optimization only; native full SLAM/DPU/GPU/performance gates remain required',
               graph_keyframe_thresholds_and_float_model_unchanged=True,protected_sha256=before,fixture=fixture_proof,
               grid_function_sha256=hashlib.sha256(body.encode()).hexdigest(),grid_changes=['read-only cell references','reserve at most64 initially; growth preserved'],
               matcher_grid_call_relocations=len(calls),source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},commands=commands,
               link_commands=dict(library=liblink,executable=exelink),units={})
    def invoke(command):
        commands.append([str(x) for x in command])
        child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while child.poll() is None:
                if available()<256*1024:
                    os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own compile stopped below256MiB available')
                time.sleep(.25)
            if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        finally:
            if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
    def compile_one(source,obj):invoke([*common,'-c',str(source),'-o',str(obj)])
    try:
        with (output/'build.log').open('w') as log:
            compile_one(output/'source/GridFixture.cc',grid_fixture)
            grid_main=output/'grid_main.o';compile_one(output/'source/check_grid_area.cc',grid_main)
            grid_check=output/'bin/check_grid_area';invoke(link_main([grid_main,grid_fixture],grid_check,base/'lib/libORB_SLAM3.so'))
            state['units']['grid']=json.loads(subprocess.check_output([str(grid_check)],text=True))
            if state['units']['grid']['status']!='EXACT_GRID_AREA_PASS' or state['units']['grid']['cases']!=32768:raise ValueError('Exact grid selection gate failed')
            bow_main=output/'bow_main.o';compile_one(output/'source/check_bow_neon.cc',bow_main)
            bow_check=output/'bin/check_bow_original';invoke(link_main([bow_main],bow_check,base/'lib/libORB_SLAM3.so'))
            state['units']['bow_reference']=json.loads(subprocess.check_output([str(bow_check),str(fixture),str(dbow)],text=True))
            if state['units']['bow_reference']['status']!='EXACT_BOW_NEON_PASS':raise ValueError('Exact word distance gate failed')
            compile_one(output/'source/FrameGrid.cc',grid);compile_one(output/'source/BowDistanceNeon.cc',bow)
            invoke(['objcopy','--weaken-symbol='+symbol,str(original),str(weak)]);invoke(liblink);invoke(exelink)
            bound=output/'bin/check_bow_bound';invoke(link_main([bow_main],bound,lib))
            state['units']['bow_bound']=json.loads(subprocess.check_output([str(bound),str(fixture),str(lib)],text=True))
            if state['units']['bow_bound']['status']!='EXACT_BOW_NEON_PASS':raise ValueError('Actual word distance binding failed')
        if strongs(weak)!={**symbols,symbol:'W'} or strongs(lib).get(symbol)!='T':raise ValueError('Unexpected retained frame symbol change')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Exact hotspot native dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained source or product changed')
        state.update(status='NATIVE_EXACT_HOTSPOTS_COMPONENT_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe,grid_check,bow_check,bound)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('root','adapter','base','fixture','output'):p.add_argument('--'+key,type=Path,required=True)
    run(**vars(p.parse_args()))
