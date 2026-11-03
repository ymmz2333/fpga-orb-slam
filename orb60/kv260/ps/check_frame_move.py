"""Native ABI, exhaustive-field, ownership and bounded Frame move experiment."""
import argparse
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import available


def transform(header):
    old='    Frame(const Frame &frame);'
    added='\n    Frame& operator=(const Frame&) = default;\n    Frame& operator=(Frame&&) = default;'
    if header.count(old)!=1 or 'operator=' in header:raise ValueError('Unreviewed retained Frame assignment boundary')
    changed=header.replace(old,old+added)
    if changed.replace(old+added,old)!=header:raise ValueError('Frame data layout or existing methods changed')
    return changed


ABI='''#include "Frame.h"
#include <cstddef>
extern "C" size_t frame_actual_size(){return sizeof(ORB_SLAM3::Frame);}
extern "C" size_t frame_actual_alignment(){return alignof(ORB_SLAM3::Frame);}
extern "C" size_t frame_actual_grid_offset(){return offsetof(ORB_SLAM3::Frame,mGrid);}
extern "C" size_t frame_actual_descriptor_offset(){return offsetof(ORB_SLAM3::Frame,mDescriptors);}
'''


def run(root,adapter,base,output):
    root,adapter,base,output=map(lambda p:Path(p).resolve(),(root,adapter,base,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 with compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text())
    if old['status']!='NATIVE_PACKED_BMP_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Explicit unchanged geometry base required')
    source=root/'slam/include/Frame.h'
    if digest(source)!='8e789448de6e26169962acf1f42a15206ed687953fee02386052e64665daf9dd':raise ValueError('Frame fixture fields require the reviewed frozen header')
    header=source.read_text();candidate=transform(header)
    before={**old['products_sha256'],str(source):digest(source)}
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained base changed')
    output.mkdir(parents=True,exist_ok=False);(output/'bin').mkdir();authored=Path(__file__).parent
    (output/'check_frame_move.cc').write_bytes((authored/'check_frame_move.cc').read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    link=list(old['link_commands']['executable']);slots=[i for i,x in enumerate(link) if x.endswith('/network.o')]
    if len(slots)!=1:raise ValueError('Unreviewed test main link')
    commands=[];state=dict(status='RUNNING',scope='PS Frame assignment component only. Every field, native layout and moved-from reuse tested. No SLAM/DPU/GPU/throughput acceptance.',
                           protected_sha256=before,source_sha256=digest(authored/'check_frame_move.cc'),commands=commands,runs=[])
    def invoke(command):
        commands.append(command);child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while child.poll() is None:
                if available()<256*1024:
                    os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own compile stopped below256MiB available')
                time.sleep(.25)
            if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        finally:
            if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
    def make_link(objects,exe):
        result=list(link);result[slots[0]:slots[0]+1]=list(map(str,objects));result[result.index('-o')+1]=str(exe);return result
    def pinned():os.sched_setaffinity(0,{3})
    try:
        with (output/'build.log').open('w') as log:
            for name,text,mode in [('reference',header,0),('candidate',candidate,1)]:
                folder=output/name;folder.mkdir();(folder/'Frame.h').write_text(text);(folder/'FrameProbe.h').write_text(text.replace('private:','public:'))
                (folder/'frame_abi.cc').write_text(ABI)
                flags_common=[common[0],'-I'+str(folder),*common[1:],'-DFRAME_MOVE_CANDIDATE='+str(mode)]
                obj=folder/'check.o';abi=folder/'abi.o';exe=output/'bin'/name
                invoke([*flags_common,'-c',str(output/'check_frame_move.cc'),'-o',str(obj)])
                invoke([*flags_common,'-c',str(folder/'frame_abi.cc'),'-o',str(abi)])
                invoke(make_link([obj,abi],exe))
            # ABBA ordering, fixed native core, same linked library and fixture.
            for i,name in enumerate(['reference','candidate','candidate','reference']):
                path=output/('%02d_%s.bin'%(i,name))
                r=json.loads(subprocess.check_output([str(output/'bin'/name),str(path),'64'],text=True,env={**os.environ,'MALLOC_CHECK_':'3'},preexec_fn=pinned,timeout=120))
                if r['status']!='FRAME_ASSIGNMENT_FIXTURE_RECORDED' or r['cases']!=128 or (name=='candidate' and r['storage_transfer_checks']!=128):raise ValueError('Incomplete Frame field/ownership gate')
                state['runs'].append(dict(mode=name,report=r,file=path.name,sha256=digest(path)))
            if len({r['sha256'] for r in state['runs']})!=1:raise ValueError('Move assignment differs from retained copy assignment')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Retained product modified')
        ref=statistics.median(r['report']['assignment_with_copy_constructor_ms_median'] for r in state['runs'] if r['mode']=='reference')
        new=statistics.median(r['report']['assignment_with_copy_constructor_ms_median'] for r in state['runs'] if r['mode']=='candidate')
        state.update(status='EXACT_FRAME_MOVE_COMPONENT_PASS',benchmark_reference_ms=ref,benchmark_candidate_ms=new,benchmark_speedup=ref/new,
                     beneficial_microbenchmark=ref/new>=1.1,header_sha256=digest(output/'candidate/Frame.h'),
                     products_sha256={str(p):digest(p) for p in (output/'bin').iterdir()})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'COMPONENT.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps({k:state[k] for k in ['status','benchmark_reference_ms','benchmark_candidate_ms','benchmark_speedup','beneficial_microbenchmark']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','output'):p.add_argument('--'+k,type=Path,required=True)
    run(**vars(p.parse_args()))
