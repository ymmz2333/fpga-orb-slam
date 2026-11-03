"""Real camera, physical7015 ORB, nativePS mapping, selected-keyframe DPU and Mali.

Explicit current-boot preflight only; no hardware loading, saved-frame/pose
fallback, CPU inference fallback, map merge or suppressed tracking losses.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import shlex
import signal
import subprocess
import time
import sys
from .camera_input import validate_calibration
from .camera_contract import validate_pair
from .run_camera_mapping import verify_build,verify_input
from .run_network_system import digest,load,save,rows
from .network_frontend import endpoint
from .two_board_session import Board,verify_current_platform,network_snapshot
from .preview_transport import PreviewTransport,validate_final_preview


def run(config_path,output,frames=300,manual_stop_file=None):
    if platform.machine()!='aarch64' or sys.platform!='linux':raise ValueError('Actual native KV260 required')
    config=load(config_path);root=Path(config['root']).resolve();out=Path(output).resolve();control=out.with_name(out.name+'_control')
    manual=manual_stop_file is not None
    if out.exists() or control.exists() or (frames!=0 if manual else not 2<=frames<=36000):raise ValueError('Fresh finite or explicitly manual camera run required')
    if manual:
        manual_stop_file=Path(manual_stop_file).resolve()
        if manual_stop_file.parent!=out.parent or manual_stop_file.exists():raise ValueError('Fresh owned manual stop file required')
    def path(key):
        p=Path(config[key]);return p if p.is_absolute() else root/p
    for key in ('source_camera','camera','yaml','vocabulary','connection','gui_python','model','placement','selection','preflight','point_preflight','point_abi','deployment_receipt'):
        if not path(key).is_file():raise ValueError('Camera system file missing: '+key)
    validate_calibration(path('source_camera'),path('camera'));validate_pair(path('camera'),path('yaml'))
    if config.get('depth_backend')!='dpu' or config.get('point_backend')!='pl' or config.get('point_memory_backend')!='native-dpu':
        raise ValueError('Explicit actual DPU and native-DPU-backed PL point projection required')
    connection=load(path('connection'));connection['kv_deployment_receipt']=str(path('deployment_receipt'))
    if endpoint(config['endpoint'])[0]!=connection['host']:raise ValueError('Physical ORB endpoint/SSH host mismatch')
    platform_proof=verify_current_platform(root,config,connection)
    protected=verify_build(path('native_build'))
    if bool(load(path('native_build')/'BUILD.json').get('manual_control',False))!=manual:
        raise ValueError('Explicit manual/finite native entry mismatch')
    control.mkdir(parents=True);save(control/'config.json',config);save(control/'connection_public.json',connection)
    state=dict(status='RUNNING',scope=__doc__,input='actual_KV260_USB3_camera',frontend='actual7015_PL',
               mapping='KV260_PS',depth_backend_selected='dpu',point_backend_selected='pl',gpu_backend_selected='Mali_GLES2',
               mapping_verified=False,hardware_inference_verified=False,frames_requested=frames,platform=platform_proof,
               config_sha256=digest(config_path),camera_sha256=digest(path('camera')),
               model_sha256=digest(path('model')),placement_sha256=digest(path('placement')),
               kernel_tainted=int(Path('/proc/sys/kernel/tainted').read_text()),manual_control=manual)
    network_snapshot(control/'network_before.json');state['network_before']=load(control/'network_before.json')
    board=Board(root,connection,control);children={};logs=[];preview=PreviewTransport('ram_bmp',out,control)
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','OPENCV_FOR_THREADS_NUM':'1',
         'ORB60_KV260_DEPTH_INTERVAL_NS':'1000000000','ORB60_MAPPER_BARRIER':'1','ORB60_NATIVE_COLOR_PREVIEW':'1',
         'ORB60_TELEMETRY_DIR':'','ORB60_TRACKING_CORE':'-1','ORB60_VIEWER_FPS':str(config.get('telemetry_fps',6)),
         'DISABLE_DPU_CONTROLLER_XRT':'1'}
    if manual:env['ORB60_MANUAL_STOP_FILE']=str(manual_stop_file)
    def start(name,command,child_env=None):
        log=(control/(name+'.log')).open('w');logs.append(log)
        child=subprocess.Popen([str(v) for v in command],cwd=root/'sources',env=child_env or env,
                               stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        children[name]=child;return child
    def wait(predicate,seconds,required):
        deadline=time.monotonic()+seconds
        while not predicate():
            for name in required:
                if children[name].poll() is not None:raise RuntimeError(name+' exited unexpectedly; see owned log')
            if time.monotonic()>deadline:raise TimeoutError('Camera stage timed out: '+','.join(required))
            time.sleep(.2)
    save(control/'RESULT.json',state)
    try:
        board.run('set -eu; test ! -e /run/orb-demo.lock; test "$(cat /sys/class/uio/uio0/version)" = wc1; '
                  'test "$(sha256sum '+shlex.quote(connection['frontend_release']+'/bin/orb60-server')+
                  ' | cut -d " " -f 1)" = '+shlex.quote(connection['frontend_sha256'])+
                  '; cat /proc/sys/kernel/random/boot_id','frontend_preflight')
        board.start_frontend();runtime_preview=preview.start();env['ORB60_TELEMETRY_DIR']=str(runtime_preview)
        depth={key:str(path(key)) for key in ('model','placement','preflight','selection','camera','point_abi','point_preflight')}
        depth.update(backend='dpu',keyframes_only=True,port=int(config.get('dense_port',18792)),linger_after_complete=True,
                     voxel_backend='packed',point_backend='pl',point_uio=config['point_uio'],point_memory_backend='native-dpu',
                     telemetry_dir=str(runtime_preview),input_kind='live_camera',allow_uninitialized_camera_completion=True,
                     defer_worker_until_first_keyframe=True)
        save(control/'depth_config.json',depth)
        native=start('native',[path('native_build')/'bin/mono_kv260_camera',path('vocabulary'),path('yaml'),config['device'],
                               path('source_camera'),config['endpoint'],out,str(frames),'1'])
        wait(lambda:(out/'dense/color_poses').is_dir(),30,('native',))
        dense=start('dense',[sys.executable,'-m','orb60.kv260.dense_service','--config',control/'depth_config.json','--run',out,'--stop-file',out/'stop_dense'])
        wait(lambda:(out/'processing_started.json').is_file(),180,('native','dense'))
        gui_env={**env,'ORB60_GUI_SOURCE_SCOPE':'two_board_live','ORB60_GUI_DEPTH_BACKEND':'dpu',
                 'ORB60_GUI_INPUT_KIND':'live_camera',
                 'ORB60_GUI_STOP_FILE':str(control/'stop_gui'),'ORB60_GUI_LIVE_STATUS':str(control/'gui_live.json'),
                 'ORB60_GUI_INPUT_IDENTITIES':'','ORB60_GUI_COLOR_IDENTITIES':'','ORB60_GUI_GPU_ONLY':'1','ORB60_GUI_FAST_PREVIEW':'1'}
        for key in ('QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_FONTDIR'):gui_env.pop(key,None)
        gui=start('gui',[path('gui_python'),'-m','orb60.kv260.gui','--dense-live','127.0.0.1:'+str(depth['port']),
                         '--frame-map',out/'source_frames.csv','--metrics',control/'gpu.json','--screenshot',control/'snapshot'],gui_env)
        deadline=None if manual else time.monotonic()+float(config.get('processing_timeout_seconds',max(180,frames/2+120)))
        while native.poll() is None:
            for name in ('dense','gui'):
                if children[name].poll() is not None:raise RuntimeError(name+' failed during camera processing')
            if manual and manual_stop_file.is_file() and deadline is None:deadline=time.monotonic()+180
            if deadline is not None and time.monotonic()>deadline:raise TimeoutError('Camera processing/explicit stop deadline exceeded')
            time.sleep(.2)
        if native.returncode:raise RuntimeError('Native camera input/mapping failed')
        if manual:
            marker=load(out/'manual_stop.json');frames=load(out/'network_mapping.json')['frames']
            if not manual_stop_file.is_file() or marker!={'status':'OPERATOR_STOP_DRAINED','frames':frames} or frames<2:
                raise ValueError('Manual map requires exact operator stop and drained frame count')
            state.update(frames_requested=frames,manual_stop=marker)
        checked=verify_input(out,frames);state['camera_input']=checked
        (out/'stop_dense').touch()
        wait(lambda:(out/'dense/status.json').is_file() and load(out/'dense/status.json')['status'] in ('COMPLETED','COMPLETED_NO_MAP_INITIALIZED'),
             240,('dense','gui'))
        result=load(out/'dense/status.json')
        def delivered():
            if not (control/'gui_live.json').is_file():return False
            s=load(control/'gui_live.json')
            if s.get('error'):raise ValueError('Camera GPU input failed: '+s['error'])
            if s.get('state')!='COMPLETED' or s.get('frame')!=frames-1:return False
            if result['status']=='COMPLETED':
                for name in result['final_pose_update']['accepted']:
                    block=load(out/'dense/blocks'/(name+'.final.json'))
                    if s.get('dense_revisions',{}).get('%d:%d'%(block['map_id'],block['keyframe_id']),0)<block['revision']:return False
                return s.get('dense_counts',[0,0])[1]>0
            return True
        wait(delivered,60,('dense','gui'))
        state['gui_live']=load(control/'gui_live.json');(control/'stop_gui').touch()
        if gui.wait(timeout=25):raise RuntimeError('Camera GPU did not close normally')
        (out/'stop_display').touch()
        if dense.wait(timeout=30):raise RuntimeError('Camera dense service did not close normally')
        gpu=load(control/'gpu.json')
        for name in ('gpu','gpu_sparse'):
            value=gpu.get(name,{})
            if value.get('software',True) or value.get('vendor')!='ARM' or 'Mali' not in value.get('renderer','') or value.get('paints',0)<1:
                raise ValueError('Actual Mali camera window not verified: '+name)
        from orb60.viewer.protocol import Snapshot
        snapshot=Snapshot.decode((control/'snapshot/frame.orbv').read_bytes());validate_final_preview(snapshot,'ram_bmp')
        tracking=rows(out/'tracking/frames.csv');last=tracking[-1]
        if snapshot.meta['frame_index']!=frames-1 or snapshot.meta['timestamp_ns']!=int(last['timestamp_ns']) or snapshot.meta['raw_gray_crc']!=int(last['gray_crc']):
            raise ValueError('Final camera preview/physical PL input mismatch')
        if snapshot.meta.get('source_gray',True):raise ValueError('Actual camera RGB preview required')
        state.update(dense=result,gpu=gpu,gpu_hardware_verified=True,hardware_inference_verified=result.get('hardware_inference_verified',False))
        if checked['valid_poses']==0:
            if result['status']!='COMPLETED_NO_MAP_INITIALIZED' or result.get('hardware_inference_verified') or result.get('maps'):
                raise ValueError('Empty camera map cannot claim DPU inference or colored geometry')
            state.update(status='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED',mapping_verified=False,
                         scope='Real camera/7015 PL/native PS/Mali startup and drain; DPU/point platform ready, no keyframes inferred or map produced')
        else:
            if result['status']!='COMPLETED' or not result.get('hardware_inference_verified') or not result.get('hardware_projection_verified'):
                raise ValueError('Camera map lacks actual DPU/PL dense geometry')
            worker=load(out/'dense/depth/worker.json')
            if worker.get('backend')!='dpu' or not worker.get('hardware_inference_verified') or worker.get('hardware_driver')!='vivado' or any(r['reused'] for r in worker['frames']):
                raise ValueError('Actual camera DPU inference receipt invalid')
            if worker.get('model_sha256')!=digest(path('model')) or len(worker['frames'])!=checked['native']['selected_keyframes'] or len(worker['frames'])!=len(result['timings']):
                raise ValueError('Camera selected keyframes/model not fully inferred')
            from .frame_store import FrameStore
            store=FrameStore(out/'dense/rgb_cache')
            for pose in (out/'dense/color_poses').glob('f*.json'):
                meta=load(pose);row=tracking[meta['source_frame_id']];store.read(meta)
                if meta['anchor_kind']!='slam_keyframe' or meta['timestamp_ns']!=int(row['timestamp_ns']) or meta['gray_crc']!=int(row['gray_crc']):
                    raise ValueError('Camera keyframe/pose/RGB identity mismatch')
            from orb60.dense.ply import read_ply
            import numpy as np
            if not result.get('maps'):raise ValueError('Camera dense map absent')
            for item in result['maps']:
                xyz,rgb=read_ply(out/'dense'/('map_%d_dense.ply'%item['map_id']))
                if len(xyz)!=item['points'] or not len(xyz) or not np.isfinite(xyz).all() or len(np.unique(rgb,axis=0))<32:
                    raise ValueError('Camera dense RGB point cloud invalid')
            for block in (out/'dense/blocks').glob('*.final.json'):
                if load(block).get('geometry_backend')!='actual_kv260_pl_point_project':raise ValueError('Camera point block lacks actual PL projection')
            if gpu.get('last_frame')!=frames-1 or gpu.get('dense_points',0)<1:raise ValueError('Camera final GPU geometry delivery incomplete')
            from .map_continuity import audit
            continuity=audit(tracking,(control/'native.log').read_text(errors='replace'))
            first=checked['first_valid_frame'];ratio=sum(int(r['pose_valid']) for r in tracking[first:])/len(tracking[first:])
            elapsed=(result['completed_monotonic_ns']-checked['native']['started_monotonic_ns'])*1e-9
            from .mapping_acceptance import evaluate
            accepted=evaluate('stable_map_5fps',dict(valid_after_initialization=ratio,frames=frames),continuity,
                              dict(all_geometry_fps=frames/elapsed),profiling=False,kernel_tainted=state['kernel_tainted'],last_pose_valid=bool(int(last['pose_valid'])))
            state.update(accepted);state.update(map_continuity=continuity,valid_after_initialization=ratio,all_geometry_fps=frames/elapsed,
                                               mapping_verified=accepted['status']=='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS')
        if any(digest(p)!=h for p,h in protected.items()):raise ValueError('Retained native camera products changed')
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:
        # Ask the owned dense process to finish any current inference before
        # terminating a stalled group. Never reset hardware or kill other jobs.
        if out.is_dir():(out/'stop_dense').touch();(out/'stop_display').touch()
        for name,child in reversed(list(children.items())):
            if child.poll() is None:
                if name=='dense':
                    try:child.wait(timeout=30)
                    except subprocess.TimeoutExpired:pass
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=15)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        for log in logs:log.close()
        try:board.stop_frontend()
        except BaseException as error:state.update(status='FAILED',frontend_cleanup_error=repr(error))
        try:state['persisted_preview']=preview.close()
        except BaseException as error:state.update(status='FAILED',preview_cleanup_error=repr(error))
        try:
            network_snapshot(control/'network_after.json');state['network_after']=load(control/'network_after.json')
        except BaseException as error:state.update(status='FAILED',network_snapshot_error=repr(error))
        state['finished_monotonic_ns']=time.monotonic_ns()
        state['available_evidence']={k:load(p) for k,p in {'dense':out/'dense/status.json','gpu':control/'gpu.json','gui_live':control/'gui_live.json'}.items() if p.is_file()}
        save(control/'RESULT.json',state)
    print(json.dumps(dict(status=state['status'],mapping_verified=state['mapping_verified'],hardware_inference_verified=state['hardware_inference_verified'])),flush=True)
    return 0 if state['status'] in ('ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED','ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS') else 2


def record_startup_failure(output,error):
    out=Path(output).resolve();control=out.with_name(out.name+'_control')
    if not out.exists() and not control.exists():
        control.mkdir(parents=True)
        save(control/'RESULT.json',dict(status='FAILED_STARTUP',error=repr(error),mapping_verified=False,
                                       hardware_inference_verified=False,scope='Camera startup checks failed; no session completion claimed'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--frames',type=int,default=300)
    p.add_argument('--manual-stop-file',type=Path)
    a=p.parse_args()
    try:code=run(a.config,a.output,a.frames,a.manual_stop_file)
    except BaseException as error:record_startup_failure(a.output,error);raise
    raise SystemExit(code)
