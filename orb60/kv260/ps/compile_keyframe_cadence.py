"""Isolated minimum keyframe spacing candidate; every video frame still tracks."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest


def extract(source, interval):
    if isinstance(interval, bool) or interval not in (5, 10, 15):
        raise ValueError('Reviewed minimum spacing required')
    signature='bool Tracking::NeedNewKeyFrame()'
    following='void Tracking::CreateNewKeyFrame()'
    if source.count(signature)!=1 or source.count(following)!=1:
        raise ValueError('Unreviewed retained keyframe selection boundary')
    body=source[source.index(signature):source.index(following,source.index(signature))].rstrip()
    old='mCurrentFrame.mnId>=mnLastKeyFrameId+mMinFrames'
    new='mCurrentFrame.mnId>=mnLastKeyFrameId+(mSensor==System::MONOCULAR ? std::max(mMinFrames,%d) : mMinFrames)'%interval
    if not body.endswith('}') or body.count('Tracking::')!=1 or body.count(old)!=1:
        raise ValueError('Ambiguous minimum frame spacing policy')
    changed=body.replace(old,new)
    if changed.replace(new,old)!=body:
        raise ValueError('Unexpected tracking policy change')
    license=source[:source.index('#include')]
    # No bridge implementation definitions are needed for this one method.
    prefix=license+''.join('#include "%s"\n'%h for h in ('Tracking.h','System.h','LocalMapping.h','Atlas.h','KeyFrame.h'))
    return prefix+'#include <algorithm>\nusing namespace std;\nnamespace ORB_SLAM3 {\n'+changed+'\n}\n',body


def run(compiler_manifest,source,output,interval):
    compiler_manifest,source,output=map(lambda p:Path(p).resolve(),(compiler_manifest,source,output))
    if platform.machine()!='x86_64':raise ValueError('PC cross compiler required')
    base=json.loads(compiler_manifest.read_text())
    if base['status']!='CROSS_OBJECT_COMPILED_REQUIRES_NATIVE_LINK_AND_BOARD_GATES':raise ValueError('Explicit cross compiler required')
    private,body=extract(source.read_bytes().decode(),interval)
    common=base['command'][:base['command'].index('-c')]
    if digest(common[0])!=base['compiler_sha256'] or any(x in common for x in ('-Ofast','-ffast-math')):raise ValueError('Compiler policy changed')
    output.mkdir(parents=True,exist_ok=False);cc=output/'NeedNewKeyFrame.cc';cc.write_bytes(private.encode());obj=output/'NeedNewKeyFrame.o'
    command=[*common,'-c',str(cc),'-o',str(obj)]
    state=dict(status='RUNNING',scope='Different monocular keyframe cadence, no skipped tracking or ORB frames; native full trajectory gates required',
               interval=interval,source_sha256=digest(source),function_sha256=hashlib.sha256(body.encode()).hexdigest(),
               private_source_sha256=digest(cc),command=command,only_minimum_idle_keyframe_interval_changed=True,
               max_interval_relocalization_outlier_and_inlier_conditions_unchanged=True)
    try:
        with (output/'build.log').open('w') as log:
            subprocess.run(['/usr/bin/time','-v','-o',str(output/'resources.txt'),*command],stdout=log,stderr=subprocess.STDOUT,check=True)
        abi=subprocess.check_output(['file',str(obj)],text=True)
        if 'ARM aarch64' not in abi:raise ValueError('Wrong object architecture')
        state.update(status='CROSS_KEYFRAME_CADENCE_COMPILED_REQUIRES_NATIVE_GATES',architecture=abi,object_sha256=digest(obj))
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'CROSS_COMPILE.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('compiler-manifest','source','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--interval',type=int,choices=(5,10,15),required=True)
    run(**vars(p.parse_args()))
