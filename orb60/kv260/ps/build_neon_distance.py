"""Native exact integer matching candidate; retains selected PS geometry objects."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
from .build_network_adapter import digest
from .build_pose_variant import available


def symbols(path,dynamic=False):
    return [line.split() for line in subprocess.check_output(['nm','-D' if dynamic else '-g','--defined-only',str(path)],text=True).splitlines() if 'DescriptorDistance' in line]


def run(root,adapter,base,fixture,output):
    root,adapter,base,fixture,output=map(lambda p:Path(p).resolve(),(root,adapter,base,fixture,output))
    if platform.machine()!='aarch64' or sys.byteorder!='little' or available()<1536*1024:raise ValueError('Native little-endian KV260 and1536MiB available required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_CROSS_POSE_LINK_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Verified explicit PS candidates required')
    before={**old['products_sha256'],**flags['products_sha256']}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained product hash changed')
    proof=json.loads(fixture.with_suffix('.json').read_text())
    if proof['cases']!=10000 or proof['sha256']!=digest(fixture):raise ValueError('Independent Hamming fixture mismatch')
    original=root/'build/CMakeFiles/ORB_SLAM3.dir/src/ORBmatcher.cc.o';before[str(original)]=digest(original)
    original_symbols=symbols(original)
    if len(original_symbols)!=1 or original_symbols[0][1]!='T':raise ValueError('Original strong distance symbol mismatch')
    name=original_symbols[0][2]
    if subprocess.check_output(['c++filt',name],text=True).strip()!='ORB_SLAM3::ORBmatcher::DescriptorDistance(cv::Mat const&, cv::Mat const&)':raise ValueError('Unreviewed distance ABI')
    output.mkdir(parents=True,exist_ok=False)
    for folder in ('source','lib','bin'):(output/folder).mkdir()
    authored=Path(__file__).parent
    for source in ('Hamming256Neon.h','NeonDescriptorDistance.cc','check_neon_distance.cc'):(output/'source'/source).write_bytes((authored/source).read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=['-I'+str(output/'source') if x.startswith('-I') and x.endswith('/source') else x for x in common]
    common+=['-mcpu=cortex-a53','-fvisibility-inlines-hidden']
    obj=output/'NeonDescriptorDistance.o';weak=output/'RetainedORBmatcher.o';lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network';check=output/'bin/check_neon_distance'
    compile_check=[common[0],'-O2','-std=gnu++14','-mcpu=cortex-a53',str(output/'source/check_neon_distance.cc'),'-o',str(check)]
    compile_wrapper=[*common,'-c',str(output/'source/NeonDescriptorDistance.cc'),'-o',str(obj)]
    liblink=list(old['commands'][1]);slot='CMakeFiles/ORB_SLAM3.dir/src/ORBmatcher.cc.o'
    if liblink.count(slot)!=1:raise ValueError('Original matcher link mismatch')
    liblink[liblink.index(slot)]=str(weak);liblink.insert(next(i for i,x in enumerate(liblink) if x.endswith('.o')),str(obj));liblink[liblink.index('-o')+1]=str(lib)
    exelink=list(old['commands'][2]);oldlib=str(base/'lib/libORB_SLAM3.so')
    if exelink.count(oldlib)!=1:raise ValueError('Selected pose library link mismatch')
    exelink[exelink.index(oldlib)]=str(lib);exelink[exelink.index('-o')+1]=str(exe)
    for i,x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands=[compile_check,compile_wrapper,['objcopy','--weaken-symbol='+name,str(original),str(weak)],liblink,exelink]
    state=dict(status='RUNNING',scope='PS integer distance only; no geometric gates changed, no hardware/performance acceptance',
               commands=commands,fixture=proof,base_geometry_build_sha256=digest(base/'BUILD.json'),
               source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},protected_sha256=before)
    try:
        with (output/'build.log').open('w') as log:
            subprocess.run(compile_check,stdout=log,stderr=subprocess.STDOUT,check=True)
            test=subprocess.check_output([str(check),str(fixture)],text=True,stderr=subprocess.STDOUT)
            numerical=json.loads(test);(output/'INTEGER_GATE.json').write_text(test)
            if numerical['status']!='NEON_EXACT_DISTANCE_PASS' or numerical['cases']!=10000:raise ValueError('Integer gate failed')
            for command in commands[1:]:subprocess.run(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        if symbols(obj)[0][1]!='T' or symbols(weak)[0][1]!='W' or symbols(lib,True)[0][1]!='T':raise ValueError('Integer symbol binding failed')
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Native dependency failure')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained product modified')
        state.update(status='NATIVE_NEON_DISTANCE_CANDIDATE_PASS',integer_gate=numerical,dependencies=deps,
                     products_sha256={str(p):digest(p) for p in (lib,exe,check)})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','base','fixture','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
