"""Finite real-camera PS mapping check with owned7015 PL, no depth substitution.

No-map completion is an explicit component result, never mapping acceptance.
Actual DPU/GPU orchestration is a separate stage after current-boot preflight.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import re
from .camera_input import validate_calibration,validate_profile
from .camera_contract import validate_pair
from .run_network_system import digest,save
from .two_board_session import Board
from .network_frontend import endpoint


def verify_build(build,env=None,linker=None):
    build=Path(build).resolve();env=dict(os.environ if env is None else env)
    if env.get('LD_PRELOAD'):raise ValueError('No native camera library preload permitted')
    receipt=json.loads((build/'BUILD.json').read_text())
    if receipt['status']!='NATIVE_CAMERA_ENTRY_BUILD_PASS':raise ValueError('Verified native camera entry required')
    protected={**receipt['protected_sha256'],**receipt['products_sha256'],str(build/'BUILD.json'):digest(build/'BUILD.json')}
    protected.update({str(build/'source'/name):h for name,h in receipt['source_sha256'].items()})
    if any(digest(p)!=h for p,h in protected.items()):raise ValueError('Camera native build changed')
    libraries=[Path(k).resolve() for k in receipt['retained_mapping_dso'] if Path(k).name=='libORB_SLAM3.so']
    exe=build/'bin/mono_kv260_camera'
    if len(libraries)!=1 or str(exe) not in receipt['products_sha256']:raise ValueError('Explicit camera executable and retained DSO required')
    if linker is None:
        def linker(command,env):return subprocess.check_output(command,env=env,text=True,stderr=subprocess.STDOUT,timeout=20)
    deps=linker(['ldd','-r',str(exe)],env=env)
    linked=re.findall(r'^\s*libORB_SLAM3\.so\s+=>\s+(.+?)\s+\(0x[0-9a-fA-F]+\)\s*$',deps,re.M)
    if 'not found' in deps or 'undefined symbol' in deps or len(linked)!=1 or Path(linked[0]).resolve()!=libraries[0]:
        raise ValueError('Camera runtime resolves a different or incomplete mapping DSO')
    return protected


def verify_input(out,expected):
    with (out/'camera_frames.csv').open(newline='') as f:sensor=list(csv.DictReader(f))
    with (out/'tracking/frames.csv').open(newline='') as f:tracking=list(csv.DictReader(f))
    profile=json.loads((out/'camera_profile.json').read_text())
    validate_profile(profile)
    if len(sensor)!=expected or len(tracking)!=expected or profile['frames']!=expected:
        raise ValueError('Incomplete actual camera/physical-feature frame coverage')
    gaps=0;valid=0
    for i,(a,b) in enumerate(zip(sensor,tracking)):
        if int(a['source_frame_id'])!=i or int(b['source_frame_id'])!=i:
            raise ValueError('Camera/SLAM sampled frame missing or reordered')
        for key in ('timestamp_ns','gray_crc'):
            if int(a[key])!=int(b[key]):raise ValueError('Camera/SLAM input identity mismatch')
        if int(b['cpu_orb_calls']) or int(b['engine_ns'])<=0 or not 0<=int(b['count'])<=1000:
            raise ValueError('Actual7015 PL result required for every frame')
        if int(a['dequeued_ns'])<int(a['timestamp_ns']):raise ValueError('Future camera timestamp')
        if i:
            previous=sensor[i-1]
            delta=(int(a['capture_sequence'])-int(previous['capture_sequence']))&0xffffffff
            if not 0<delta<0x80000000 or int(a['timestamp_ns'])<=int(previous['timestamp_ns']):
                raise ValueError('Sensor frame duplicated/backwards')
            gaps+=delta-1
        if int(a['sequence_gaps'])!=gaps:raise ValueError('Camera drops concealed or incorrectly counted')
        valid+=int(b['pose_valid'])
        if int(b['pose_valid']) not in (0,1):raise ValueError('Invalid pose-valid flag')
    if profile['sequence_gaps']!=gaps or not (out/'CAMERA_INPUT_COMPLETE').is_file():
        raise ValueError('Camera profile/journal/drain mismatch')
    state=json.loads((out/'camera_mapping_status.json').read_text())
    mapping=json.loads((out/'network_mapping.json').read_text())
    if mapping['frames']!=expected or mapping['valid_poses']!=valid or mapping['cpu_orb_calls']:
        raise ValueError('Native result/journal mismatch')
    if state['mapping_verified'] is not False:
        raise ValueError('Camera input gate cannot assert full motion/stability acceptance')
    if valid==0:
        if state['status']!='INPUT_DRAINED_NO_MAP_INITIALIZED' or (out/'NATIVE_COMPLETE').exists() or (out/'tracking/map/EXPORT_COMPLETE').exists():
            raise ValueError('No-map state cannot be relabeled as mapping success')
    elif state['status']!='CAMERA_MAP_EXPORTED_VALIDATION_PENDING' or not (out/'NATIVE_COMPLETE').is_file():
        raise ValueError('Camera map export status incomplete')
    return dict(frames=expected,valid_poses=valid,raw_sequence_gaps=gaps,cpu_orb_calls=0,
                camera_profile=profile,native=mapping,map_status=state,
                first_valid_frame=next((i for i,r in enumerate(tracking) if int(r['pose_valid'])),None))


def run(a):
    root=a.root.resolve();build=a.build.resolve();out=a.output.resolve();control=out.with_name(out.name+'_control')
    if not 2<=a.frames<=36000 or out.exists() or control.exists():
        raise ValueError('Finite frames and fresh output/control directories required')
    validate_calibration(a.source_camera,a.camera);validate_pair(a.camera,a.yaml)
    protected=verify_build(build)
    connection=json.loads(a.connection.read_text())
    if endpoint(a.endpoint)[0]!=connection['host']:raise ValueError('Physical ORB and SSH peer differ')
    control.mkdir(parents=True)
    state=dict(status='RUNNING',scope=__doc__,input='actual_KV260_USB3_camera',frontend='actual7015_PL',mapping='KV260_PS',
               dpu_used=False,gpu_used=False,frames_requested=a.frames,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               yaml_sha256=digest(a.yaml),source_calibration_sha256=digest(a.source_camera),working_calibration_sha256=digest(a.camera),
               build_receipt_sha256=digest(build/'BUILD.json'),camera_calibration=dict(fps=60,crop_x=160,source_width=1280,source_height=720))
    board=Board(root,connection,control);child=None
    save(control/'RESULT.json',state)
    try:
        board.run('set -eu; test ! -e /run/orb-demo.lock; test "$(cat /sys/class/uio/uio0/version)" = wc1; '
                  'test "$(sha256sum '+shlex.quote(connection['frontend_release']+'/bin/orb60-server')+
                  ' | cut -d " " -f 1)" = '+shlex.quote(connection['frontend_sha256'])+
                  '; cat /proc/sys/kernel/random/boot_id','frontend_preflight')
        board.start_frontend()
        env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','OPENCV_FOR_THREADS_NUM':'1',
             'ORB60_KV260_DEPTH_INTERVAL_NS':'1000000000','ORB60_MAPPER_BARRIER':'1',
             'ORB60_NATIVE_COLOR_PREVIEW':'0','ORB60_TELEMETRY_DIR':'','ORB60_TRACKING_CORE':'-1'}
        command=[str(build/'bin/mono_kv260_camera'),str(a.vocabulary.resolve()),str(a.yaml.resolve()),a.device,
                 str(a.source_camera.resolve()),a.endpoint,str(out),str(a.frames),'0']
        state['command']=command;save(control/'RESULT.json',state)
        with (control/'native.log').open('w') as log:
            child=subprocess.Popen(command,cwd=root/'build',env=env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+max(180,a.frames/2+120)
            while child.poll() is None:
                if time.monotonic()>deadline:raise TimeoutError('Finite native camera run deadline exceeded')
                time.sleep(.5)
        state['native_exit_code']=child.returncode
        if child.returncode:raise RuntimeError('Native camera/PS mapping failed; see owned native.log')
        state['verification']=verify_input(out,a.frames)
        state['mapping_verified']=False
        state['status']=('ACTUAL_CAMERA_NATIVE_INPUT_PASS_NO_MAP_INITIALIZED' if state['verification']['valid_poses']==0
                         else 'ACTUAL_CAMERA_MAP_EXPORTED_VALIDATION_PENDING')
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:
        cleanup=[]
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        try:board.stop_frontend()
        except BaseException as error:cleanup.append(repr(error))
        if cleanup:state.update(status='FAILED',cleanup_errors=cleanup)
        state['retained_products_unchanged']=all(digest(p)==h for p,h in protected.items())
        if not state['retained_products_unchanged']:state.update(status='FAILED',protected_products_changed=True)
        save(control/'RESULT.json',state)
        if cleanup:raise RuntimeError('Owned camera frontend cleanup failed: '+str(cleanup))
        if not state['retained_products_unchanged']:raise RuntimeError('Protected native products changed')
    print(json.dumps(state),flush=True)
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','build','vocabulary','yaml','source-camera','camera','connection','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--endpoint',required=True);p.add_argument('--device',default='/dev/video0')
    p.add_argument('--frames',type=int,default=300)
    run(p.parse_args())
