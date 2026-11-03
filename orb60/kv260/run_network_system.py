"""Concurrent physical 7015 ORB + KV260 PS mapping, actual DPU and Mali display.

Run through depth/runtime_exec.sh with the private native VAI runtime. No board
programming, CPU ORB/depth fallback, saved poses, or substituted features.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path=Path(path);part=path.with_suffix('.part')
    part.write_text(json.dumps(value,indent=2)+'\n');part.replace(path)


def rows(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def check_frames(actual, identities, reference):
    """Read-only verification against frozen input and physical feature CRCs."""
    if not actual or len(actual)!=len(identities) or len(reference)<len(actual):
        raise ValueError('Incomplete source or reference frame coverage')
    for i,(a,b,c) in enumerate(zip(actual,identities,reference)):
        if int(a['source_frame_id'])!=i or int(b['source_frame_id'])!=i or int(c['source_frame_id'])!=i:
            raise ValueError('Source frame missing, repeated or reordered')
        for key in ('timestamp_ns','gray_crc'):
            if int(a[key])!=int(b[key]) or int(a[key])!=int(c[key]):
                raise ValueError('Frozen frame identity mismatch: %s frame%d'%(key,i))
        for key in ('record_crc','count'):
            if int(a[key])!=int(c[key]):raise ValueError('Physical ORB result mismatch: %s frame%d'%(key,i))
        if int(a['cpu_orb_calls']) or not 0<=int(a['count'])<=1000:
            raise ValueError('CPU ORB fallback or invalid feature count')
    first=next((i for i,r in enumerate(actual) if int(r['pose_valid'])),None)
    if first is None:raise ValueError('SLAM never initialized')
    ratio=sum(int(r['pose_valid']) for r in actual[first:])/len(actual[first:])
    return {'frames':len(actual),'first_valid_frame':first,'valid_after_initialization':ratio,
            'source_identity_mismatches':0,'physical_feature_mismatches':0,'cpu_orb_calls':0}


def run(config_path, output, frames=0):
    if platform.machine()!='aarch64' or not sys.platform.startswith('linux'):
        raise ValueError('Actual native KV260 required')
    config=load(config_path);root=Path(config['root']).resolve();out=Path(output).resolve()
    control=out.with_name(out.name+'_control')
    if out.exists() or control.exists():raise ValueError('Fresh run and control directories required')
    def path(key):
        value=Path(config[key]);return value if value.is_absolute() else root/value
    decoder_mode=config.get('decoder_mode','slice');uncompressed=decoder_mode=='uncompressed'
    raw_transport=config.get('uncompressed_transport','file')
    if raw_transport not in ('file','emulated_stream'):raise ValueError('Explicit uncompressed transport required')
    sensor_stream=uncompressed and raw_transport=='emulated_stream'
    required=('identities','reference_features','executable','vocabulary','yaml','gui_python','model','placement','preflight','selection','camera')
    for key in required+(() if uncompressed else ('video',)):
        if not path(key).is_file():raise ValueError('Required file missing: '+key)
    if decoder_mode not in ('slice','frame_repair','paired_frame_repair','uncompressed'):raise ValueError('Explicit supported video decoder mode required')
    gray_mode=config.get('gray_input','bgr_to_gray')
    if gray_mode not in ('bgr_to_gray','pyav_direct_gray'):raise ValueError('Explicit video gray input required')
    direct_gray=gray_mode=='pyav_direct_gray'
    if direct_gray:
        if decoder_mode not in ('slice','paired_frame_repair','uncompressed') or not config.get('native_build') or not config.get('native_color_preview',False):
            raise ValueError('Paired direct gray requires explicit SLICE source, native build and original RGB preview')
        if not uncompressed:
            from .direct_gray import validate
            validate(path('direct_gray_proof'),path('video'),path('identities'),path('color_identities'),path('reference_features'))
    if uncompressed:
        if not direct_gray:raise ValueError('Uncompressed replay requires explicit original-gray contract')
        if sensor_stream:
            from .packed_stream import validate_contract
            stream_source,packed_source=validate_contract(path('packed_stream_proof'),path('packed_proof'),path('packed_headers'),path('identities'),path('color_identities'),path('reference_features'),path('packed_gray_lut'))
            from .ps.verify_packed_stream import validate_native
            validate_native(path('packed_native_proof'),path('packed_proof'),path('packed_stream_proof'),path('executable'))
        else:
            from .packed_yuv import validate
            packed_source=validate(path('packed_proof'),path('raw_input'),path('identities'),path('color_identities'),path('reference_features'),path('packed_gray_lut'))
            from .ps.verify_packed_yuv import validate_native
            validate_native(path('packed_native_proof'),path('packed_proof'),path('executable'))
    lossless_info=None
    if config.get('lossless_source_proof'):
        if not sensor_stream or frames:raise ValueError('Lossless byte emulator requires full native sensor-stream input')
        from .lossless_sensor_stream import validate as validate_lossless
        lossless_info,_=validate_lossless(path('lossless_source_proof'),path('packed_stream_proof'),path('packed_headers'))
    if decoder_mode=='paired_frame_repair':
        if not direct_gray:raise ValueError('Paired decoder requires direct-gray and RGB inputs')
        from .paired_frame_decoder import validate_proof
        validate_proof(path('paired_decoder_proof'),path('video'),path('identities'),path('color_identities'),path('direct_gray_proof'),path('paired_decoder_plan'))
    initial_reference=config.get('initial_reference_source',0)
    if type(initial_reference)!=int or initial_reference not in (0,24):raise ValueError('Explicit supported initialization reference required')
    mapper_mode=config.get('mapper_wait_mode','idle' if config.get('mapper_barrier',False) else 'none')
    if mapper_mode not in ('none','idle','published') or (mapper_mode!='none')!=bool(config.get('mapper_barrier',False)):
        raise ValueError('Explicit matching mapper scheduling mode required')
    preview_backend=config.get('preview_transport','file_jpeg')
    if preview_backend not in ('file_jpeg','ram_bmp'):raise ValueError('Explicit preview transport required')
    if preview_backend=='ram_bmp' and (not config.get('native_build') or not config.get('native_color_preview',False)):
        raise ValueError('RAM BMP requires an explicit native build and original color preview')
    if decoder_mode=='frame_repair':
        if config.get('decoder_reuse_converter',False):raise ValueError('Unreviewed combined decoder converter mode')
        from .frame_decoder import validate_proof
        validate_proof(path('decoder_repair_proof'),path('video'),path('identities'),path('decoder_repair_plan'))
    proof=load(path('preflight'))
    if proof.get('status')!='PROFILE_MATCH' or proof.get('driver')!='vivado':
        raise ValueError('This native Vivado deployment requires a matching driver proof')
    identities=rows(path('identities'));source_frames_total=len(identities)
    if frames<0 or frames>len(identities):raise ValueError('Invalid frame limit')
    if frames:identities=identities[:frames]
    if not identities:raise ValueError('Empty input')
    control.mkdir(parents=True);fifo=control/'original_bgr.fifo'
    if not uncompressed:os.mkfifo(fifo,0o600)
    report={'status':'RUNNING','scope':'concurrent physical two-board video processing',
            'frontend':'actual_zynq7015_PL','mapping':'KV260_PS','depth':'actual_KV260_DPU',
            'fusion':'KV260_PS','display':'KV260_Mali_GLES2','frames_requested':len(identities),'source_frames_total':source_frames_total,
            'started_monotonic_ns':time.monotonic_ns(),'config':config,'pids':{}}
    report['kernel_tainted']=int(Path('/proc/sys/kernel/tainted').read_text())
    authored=Path(__file__).resolve().parent
    report['source_sha256']={str(p.relative_to(authored.parents[1])):digest(p) for p in (
        authored/'run_network_system.py',authored/'dense_service.py',authored/'dense_fusion.py',authored/'mapping_acceptance.py',authored/'map_continuity.py',
        authored/'voxel.py',authored.parent/'dense/geometry.py',authored/'gui.py',authored/'gui_worker.py',
        authored/'source_frame_map.py',authored/'video_preview.py',authored/'feature_overlay.py',
        authored/'cpu_policy.py',authored/'video_pipe.py',authored/'video_conversion.py',authored/'frame_decoder.py',authored/'native_products.py',authored/'preview_transport.py',authored/'tracking_trace.py',authored.parent/'viewer/app.py')}
    if direct_gray:report['source_sha256'][str((authored/'direct_gray.py').relative_to(authored.parents[1]))]=digest(authored/'direct_gray.py')
    if decoder_mode=='paired_frame_repair':report['source_sha256'][str((authored/'paired_frame_decoder.py').relative_to(authored.parents[1]))]=digest(authored/'paired_frame_decoder.py')
    if uncompressed:
        selected=(authored/'packed_stream.py',authored/'ps/verify_packed_stream.py') if sensor_stream else (authored/'ps/verify_packed_yuv.py',)
        for p in (authored/'packed_yuv.py',*selected):report['source_sha256'][str(p.relative_to(authored.parents[1]))]=digest(p)
        report['input_scope']=('PC temporarily emulates sensor bytes only; native TCP receive, luma/color conversion and all computation remain on boards; NOT final standalone/direct cable acceptance' if sensor_stream else 'Native uncompressed '+packed_source['format']+' recorded replay; includes raw-file I/O, luma and color conversion; not live camera capture')
    if lossless_info:
        report['input_scope']+='; offline LZ4 encodes transport bytes only, KV260 PS restores the exact original packed input before native processing'
        report['lossless_source_proof_sha256']=digest(path('lossless_source_proof'))
        for p in (authored/'lossless_sensor_stream.py',authored/'sensor_compression.py'):report['source_sha256'][str(p.relative_to(authored.parents[1]))]=digest(p)
    report['profiling']=bool(config.get('profile',False))
    from .cpu_policy import validate_policy
    policy=validate_policy(config,os.sched_getaffinity(0))
    children={};logs=[];native_end=None;gui=None;preview=None;decoder=None
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','OPENCV_FOR_THREADS_NUM':'1',
         'ORB60_VIEWER_FPS':str(config.get('telemetry_fps',10)),
         'ORB60_KV260_DEPTH_INTERVAL_NS':str(config.get('depth_interval_ns',1000000000)),
         'ORB60_NATIVE_COLOR_PREVIEW':'1' if config.get('native_color_preview',False) else '0',
         'ORB60_TRACKING_TRACE':'1' if config.get('tracking_trace',False) else '0',
         'ORB60_MOTION_POSE_POLICY':config.get('motion_pose_policy','original'),
         'ORB60_MOTION_POSE_REPORT':str(control/'motion_pose.json'),
         'ORB60_TELEMETRY_DIR':'',
         'ORB60_PACKED_GRAY_LUT':str(path('packed_gray_lut')) if uncompressed else '',
         'ORB60_PACKED_VERIFY_COLOR_CSV':'',
         'ORB60_PACKED_HEADERS':str(path('packed_headers')) if sensor_stream else '',
         'ORB60_PACKED_STREAM_SHA256':stream_source['data_sha256'] if sensor_stream else '',
         'ORB60_PACKED_STREAM_STATUS':str(control/'sensor_source.json') if sensor_stream else '',
         'ORB60_DECODER_REUSE_CONVERTER':'1' if config.get('decoder_reuse_converter',False) else '0',
         'ORB60_VIDEO_REPAIR_PLAN':str(path('decoder_repair_plan')) if decoder_mode=='frame_repair' else '',
         'ORB60_VIDEO_REPAIR_PROOF':str(path('decoder_repair_proof')) if decoder_mode=='frame_repair' else '',
         'ORB60_MAPPER_BARRIER':'1' if config.get('mapper_barrier',False) else '0',
         'ORB60_TRACKING_CORE':str(policy[0]) if policy else '-1',
         'ORB60_BACKGROUND_CPUS':','.join(map(str,policy[1])) if policy else '',
         'DISABLE_DPU_CONTROLLER_XRT':'1'}
    def start(command,name,child_env=None):
        log=(control/(name+'.log')).open('w');logs.append(log)
        def scheduling():
            if policy and name!='decoder':os.sched_setaffinity(0,set(policy[1]))
            nice=int(config.get(name+'_nice',0))
            if nice:
                if not 0<=nice<=19:raise ValueError('Only nonnegative per-child nice supported')
                os.nice(nice)
        child=subprocess.Popen([str(x) for x in command],stdout=log,stderr=subprocess.STDOUT,
                               env=child_env or env,cwd=control if name=='native' else root/'sources',start_new_session=True,
                               preexec_fn=scheduling if policy or config.get(name+'_nice',0) else None)
        children[name]=child;report['pids'][name]=child.pid;save(control/'RESULT.json',report)
        return child
    def alive(name):
        child=children.get(name)
        if child and child.poll() is not None:raise RuntimeError('%s exited unexpectedly (%s); see owned log'%(name,child.returncode))
    def wait_for(predicate,seconds,required):
        deadline=time.monotonic()+seconds
        while not predicate():
            for name in required:alive(name)
            if time.monotonic()>deadline:raise TimeoutError('Stage deadline expired: '+','.join(required))
            time.sleep(.25)
    try:
        if config.get('native_build'):
            from .native_products import verify
            report['native_products']=verify(path('native_build'),path('executable'),env)
        build_status=report.get('native_products',{}).get('build_status')
        from .tracking_trace import validate_config as validate_trace
        trace_enabled=validate_trace(config,build_status)
        report['tracking_trace_enabled']=trace_enabled
        from .motion_pose_policy import validate as validate_motion
        motion_policy=validate_motion(config,build_status);report['motion_pose_policy']=motion_policy
        if motion_policy!='original':
            for p in (authored/'motion_pose_policy.py',authored/'ps/MotionPosePolicy.h',authored/'ps/motion_pose_transform.py'):report['source_sha256'][str(p.relative_to(authored.parents[1]))]=digest(p)
        if direct_gray!=(build_status in ('NATIVE_DIRECT_GRAY_COMPONENT_PASS','NATIVE_REFERENCE_SEED_COMPONENT_PASS','NATIVE_PACKED_YUV_COMPONENT_PASS','NATIVE_PACKED_STREAM_COMPONENT_PASS','NATIVE_PACKED_ARM_CRC_COMPONENT_PASS','NATIVE_PACKED_BMP_COMPONENT_PASS','NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS','NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS','NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS','NATIVE_TRACKING_TRACE_BUILD_PASS','NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS')):
            raise ValueError('Selected native executable/input gray mode mismatch')
        if uncompressed!=(build_status in ('NATIVE_PACKED_YUV_COMPONENT_PASS','NATIVE_PACKED_STREAM_COMPONENT_PASS','NATIVE_PACKED_ARM_CRC_COMPONENT_PASS','NATIVE_PACKED_BMP_COMPONENT_PASS','NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS','NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS','NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS','NATIVE_TRACKING_TRACE_BUILD_PASS','NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS')):raise ValueError('Selected native uncompressed input mismatch')
        if build_status!='NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS' and sensor_stream!=(build_status in ('NATIVE_PACKED_STREAM_COMPONENT_PASS','NATIVE_PACKED_ARM_CRC_COMPONENT_PASS','NATIVE_PACKED_BMP_COMPONENT_PASS','NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS','NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS','NATIVE_TRACKING_TRACE_BUILD_PASS','NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS')):raise ValueError('Selected sensor-stream native input mismatch')
        if (initial_reference==24)!=(build_status=='NATIVE_REFERENCE_SEED_COMPONENT_PASS'):
            raise ValueError('Selected native initialization reference mismatch')
        bmp_builds=('NATIVE_RAM_BMP_PREVIEW_COMPONENT_PASS','NATIVE_PACKED_BMP_COMPONENT_PASS','NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS','NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS','NATIVE_PACKED_BOUNDED_MAPPER_COMPONENT_PASS','NATIVE_TRACKING_TRACE_BUILD_PASS','NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS')
        if preview_backend=='ram_bmp' and report['native_products']['build_status'] not in bmp_builds:
            raise ValueError('Selected native executable does not declare the RAM BMP producer')
        if preview_backend!='ram_bmp' and report.get('native_products',{}).get('build_status') in bmp_builds:
            raise ValueError('Selected RAM BMP executable requires the matching preview transport')
        from .preview_transport import PreviewTransport
        preview=PreviewTransport(preview_backend,out,control)
        runtime_preview=preview.start()
        report['preview_transport']={'backend':preview_backend,'codec':'bmp' if runtime_preview else 'jpeg'}
        if runtime_preview:
            env['ORB60_TELEMETRY_DIR']=str(runtime_preview)
            report['preview_transport']['runtime_directory']=str(runtime_preview)
        depth={key:str(path(key)) for key in ('model','placement','preflight','selection','camera')}
        depth.update(backend='dpu',keyframes_only=True,port=int(config.get('dense_port',18790)),linger_after_complete=True,
                     voxel_backend=config.get('voxel_backend','reference'),point_backend=config.get('point_backend','ps'))
        if depth['point_backend'] not in ('ps','pl'):raise ValueError('Explicit ps/pl projection backend required')
        if depth['point_backend']=='pl':
            for key in ('point_uio','point_abi','point_preflight'):depth[key]=str(path(key))
            depth['point_memory_backend']=config['point_memory_backend']
            report['fusion']='KV260_PL_projection_plus_PS_fit_consistency_voxels'
            report['point_preflight_sha256']=digest(path('point_preflight'))
            for p in (authored/'point_pl/runtime.py',authored/'point_pl/fusion.py',authored/'point_pl/reference.py',authored/'point_pl/native_memory.py'):
                report['source_sha256'][str(p.relative_to(authored.parents[1]))]=digest(p)
        if runtime_preview:depth['telemetry_dir']=str(runtime_preview)
        save(control/'depth_config.json',depth)
        if not uncompressed:
            decoder_command=[sys.executable,'-m','orb60.kv260.direct_gray','stream'] if direct_gray else [sys.executable,'-m','orb60.kv260.video_pipe']
            if decoder_mode=='paired_frame_repair':decoder_command=[sys.executable,'-m','orb60.kv260.paired_frame_decoder','stream']
            decoder_command+=['--video',path('video'),'--fifo',fifo,'--identities',path('identities'),'--frames',str(frames),'--summary',control/'decoder.json']
            if direct_gray:decoder_command+=['--color-identities',path('color_identities'),'--proof',path('direct_gray_proof')]
            if decoder_mode=='paired_frame_repair':decoder_command+=['--plan',path('paired_decoder_plan'),'--decoder-proof',path('paired_decoder_proof')]
            decoder=start(decoder_command,'decoder')
        if sensor_stream:native_input=packed_source['format'].lower()+':listen:'+config['raw_endpoint']
        elif uncompressed:native_input=packed_source['format'].lower()+':'+str(path('raw_input'))
        else:native_input=('paired:' if direct_gray else 'pipe:')+str(fifo)
        native=start([path('executable'),path('vocabulary'),path('yaml'),native_input,path('identities'),
                      config['endpoint'],out,str(frames),'1'],'native')
        wait_for(lambda:(out/'dense/color_poses').is_dir(),30,('native',))
        dense_python=[sys.executable]
        if report['profiling']:dense_python+=['-m','cProfile','-o',str(control/'dense.profile')]
        dense=start([*dense_python,'-m','orb60.kv260.dense_service','--config',control/'depth_config.json',
                     '--run',out,'--stop-file',out/'stop_dense'],'dense')
        wait_for(lambda:(out/'processing_started.json').is_file(),180,('native','dense'))
        gui_env=env.copy();gui_env.update(ORB60_GUI_SOURCE_SCOPE='two_board_live',ORB60_GUI_DEPTH_BACKEND='dpu',
                         ORB60_GUI_STOP_FILE=str(control/'stop_gui'),ORB60_GUI_LIVE_STATUS=str(control/'gui_live.json'),
                         ORB60_GUI_INPUT_IDENTITIES=str(path('identities')))
        gui_env['ORB60_GUI_COLOR_IDENTITIES']=str(path('color_identities')) if direct_gray else ''
        for key in ('QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_FONTDIR'):gui_env.pop(key,None)
        gui_env['ORB60_GUI_BATCH_FEATURES']='1' if config.get('batch_feature_overlay',False) else '0'
        gui_env['ORB60_GUI_FAST_PREVIEW']='1' if config.get('fast_preview',True) else '0'
        gui_env['ORB60_GUI_GPU_ONLY']='1' if config.get('gpu_only',True) else '0'
        report['display_mode']='gpu_maps_only' if config.get('gpu_only',True) else 'full_ui'
        if report['profiling']:gui_env['ORB60_GUI_PROFILE']=str(control/'gui.profile')
        gui_video=[] if config.get('native_color_preview',False) else ['--video',path('video')]
        gui=start([path('gui_python'),'-m','orb60.kv260.gui','--dense-live','127.0.0.1:'+str(depth['port']),
                   *gui_video,'--frame-map',out/'source_frames.csv',
                   '--metrics',control/'gpu.json','--screenshot',control/'snapshot'], 'gui',gui_env)
        deadline=time.monotonic()+float(config.get('processing_timeout_seconds',600))
        while native.poll() is None:
            alive('dense');alive('gui')
            if decoder is not None and decoder.poll() is not None and decoder.returncode:raise RuntimeError('Decoder failed')
            if time.monotonic()>deadline:raise TimeoutError('Native mapping did not finish')
            time.sleep(.25)
        native_end=time.monotonic_ns()
        if native.returncode:raise RuntimeError('Native mapping failed; see native.log')
        if decoder is not None and decoder.wait(timeout=15):raise RuntimeError('Decoder failed to drain')
        if not (out/'NATIVE_COMPLETE').is_file() or not (out/'tracking/map/EXPORT_COMPLETE').is_file():
            raise ValueError('Final optimized map incomplete')
        if uncompressed:
            m=load(out/'network_mapping.json')
            if m.get('input_format')!=packed_source['format']:raise ValueError('Native packed pixel format mismatch')
            backend='KV260_PS_NATIVE_PACKED_FILE'
            if sensor_stream:
                trace=load(control/'sensor_source.json')
                if trace.get('transport')!='tcp_camera_emulator' or trace.get('master_sha256')!=stream_source['data_sha256'] or trace.get('headers_verified',0)<len(identities) or (not frames and trace.get('status')!='DRAINED'):
                    raise ValueError('Sealed sensor source did not drain requested original frames')
                backend='KV260_PS_NATIVE_SENSOR_BYTE_STREAM';report['sensor_source']=trace
            save(control/'decoder.json',dict(status='ORIGINAL_UNCOMPRESSED_VIDEO_DRAINED',backend=backend,format=packed_source['format'],frames=m['frames'],source_proof_sha256=digest(path('packed_proof'))))
        (out/'stop_dense').touch()
        wait_for(lambda:(out/'dense/status.json').is_file() and load(out/'dense/status.json')['status']=='COMPLETED',
                 240,('dense','gui'))
        dense_result=load(out/'dense/status.json')
        def delivered():
            state=load(control/'gui_live.json') if (control/'gui_live.json').is_file() else {}
            if state.get('error'):raise ValueError('Live GPU source failed: '+state['error'])
            if state.get('state')!='COMPLETED' or state.get('frame')!=len(identities)-1:return False
            for name in dense_result['final_pose_update']['accepted']:
                block=load(out/'dense/blocks'/(name+'.final.json'))
                if state.get('dense_revisions',{}).get('%d:%d'%(block['map_id'],block['keyframe_id']),0)<block['revision']:return False
            return state.get('dense_counts',[0,0])[1]>0
        wait_for(delivered,60,('dense','gui'))
        delivered_ns=time.monotonic_ns();report['gui_live']=load(control/'gui_live.json')
        (control/'stop_gui').touch()
        if gui.wait(timeout=20):raise RuntimeError('GPU viewer did not close normally')
        (out/'stop_display').touch()
        if dense.wait(timeout=15):raise RuntimeError('Dense service did not close normally')
        mapping=load(out/'network_mapping.json');decode=load(control/'decoder.json');gpu=load(control/'gpu.json')
        if direct_gray and mapping.get('gray_input')!='pyav_direct_gray':raise ValueError('Native direct-gray input not declared')
        if mapping.get('initial_reference_source',0)!=initial_reference:raise ValueError('Native initialization reference not matched')
        if initial_reference:
            event=load(out/'initial_reference.json')
            if event.get('source_frame')!=24 or event.get('preceding_PL_PS_frames')!=24 or event.get('prior_tracking_state') not in (0,1) or event.get('prior_keyframes')!=0 or event.get('prior_points')!=0:
                raise ValueError('Initialization reset did not preserve processed frames or empty-map guard')
        if bool(mapping.get('native_color_preview',False))!=bool(config.get('native_color_preview',False)):
            raise ValueError('Native color preview executable/config mismatch')
        if bool(mapping.get('mapper_barrier',False))!=bool(config.get('mapper_barrier',False)):
            raise ValueError('Native mapper scheduling executable/config mismatch')
        actual_mapper_mode=mapping.get('mapper_wait_mode','idle' if mapping.get('mapper_barrier',False) else 'none')
        if actual_mapper_mode!=mapper_mode:raise ValueError('Native mapper wait semantics do not match the selected mode')
        if int(mapping.get('tracking_cpu_core',-1))!=(policy[0] if policy else -1):raise ValueError('Tracking affinity/config mismatch')
        from orb60.viewer.protocol import Snapshot
        final_preview=Snapshot.decode((control/'snapshot/frame.orbv').read_bytes())
        from .source_frame_map import FrozenFrameIdentities
        FrozenFrameIdentities(path('identities'),path('color_identities') if direct_gray else None).check(final_preview.meta)
        from .preview_transport import validate_final_preview
        validate_final_preview(final_preview,preview_backend)
        if config.get('native_color_preview',False) and final_preview.meta['source_gray']:
            raise ValueError('Native preview is not the paired original color frame')
        actual=rows(out/'tracking/frames.csv');checked=check_frames(actual,identities,rows(path('reference_features')))
        from .map_continuity import audit
        continuity=audit(actual,(control/'native.log').read_text(errors='replace'))
        report['map_continuity']=continuity
        save(control/'map_continuity.json',continuity)
        if motion_policy!='original':
            from .motion_pose_policy import check as check_motion
            report['motion_pose_counters']=check_motion(control/'motion_pose.json',len(actual))
        if lossless_info:
            from .lossless_sensor_stream import verify_receipt
            receipt=verify_receipt(path('lossless_source_proof'),path('packed_stream_proof'),path('packed_headers'),control/'lossless_source.json')
            if receipt['helper_sha256']!=digest(authored/'lossless_sensor_stream.py') or receipt['codec_wrapper_sha256']!=digest(authored/'sensor_compression.py'):raise ValueError('Lossless source helper changed during execution')
            report['lossless_source']=receipt
        if trace_enabled:
            from .tracking_trace import check as check_trace
            report['tracking_trace']=check_trace(out/'tracking',actual)
        expected_decode='ORIGINAL_UNCOMPRESSED_VIDEO_DRAINED' if uncompressed else 'ORIGINAL_VIDEO_FIFO_DRAINED'
        if decode['status']!=expected_decode or decode['frames']!=len(actual) or mapping['frames']!=len(actual):
            raise ValueError('Incomplete native/decoder drain')
        worker=load(out/'dense/depth/worker.json')
        if worker.get('backend')!='dpu' or not worker.get('hardware_inference_verified') or worker.get('hardware_driver')!='vivado':
            raise ValueError('Actual native DPU not verified')
        if worker['model_sha256']!=digest(path('model')) or any(r['reused'] for r in worker['frames']):
            raise ValueError('Wrong model or reused depth inference')
        if len(worker['frames'])!=len(dense_result['timings']) or len(worker['frames'])!=mapping['selected_keyframes']:
            raise ValueError('Selected keyframes not fully inferred')
        if depth['point_backend']=='pl':
            if dense_result.get('point_backend')!='pl' or not dense_result.get('hardware_projection_verified') or not dense_result.get('projection_timings'):
                raise ValueError('Actual PL projection was selected but not executed')
            for block in (out/'dense/blocks').glob('*.final.json'):
                if load(block).get('geometry_backend')!='actual_kv260_pl_point_project':raise ValueError('Final point block did not use PL geometry')
        from .frame_store import FrameStore
        store=FrameStore(out/'dense/rgb_cache')
        color_rows=rows(path('color_identities')) if direct_gray else None
        for pose_path in (out/'dense/color_poses').glob('f*.json'):
            meta=load(pose_path);i=int(meta['source_frame_id']);paired_rgb=store.read(meta)
            if color_rows is not None:
                import zlib
                if zlib.crc32(paired_rgb.tobytes())!=int(color_rows[i]['bgr_crc']):raise ValueError('Selected DPU RGB pixels differ from original source contract')
            if meta['anchor_kind']!='slam_keyframe' or meta['timestamp_ns']!=int(identities[i]['timestamp_ns']):
                raise ValueError('Keyframe RGB/pose identity mismatch')
        import numpy as np
        from orb60.dense.ply import read_ply
        for item in dense_result['maps']:
            xyz,rgb=read_ply(out/'dense'/('map_%d_dense.ply'%item['map_id']))
            if len(xyz)!=item['points'] or not len(xyz) or not np.isfinite(xyz).all() or len(np.unique(rgb,axis=0))<32:
                raise ValueError('Final RGB point cloud invalid')
        for key in ('gpu','gpu_sparse'):
            value=gpu.get(key,{})
            if value.get('software',True) or value.get('vendor')!='ARM' or 'Mali' not in value.get('renderer','') or value.get('paints',0)<1:
                raise ValueError('Independent Mali window not verified: '+key)
        if gpu['last_frame']!=len(actual)-1 or gpu.get('dense_points',0)<1:raise ValueError('GPU final source/point delivery incomplete')
        if report.get('native_products'):
            from .native_products import check_unchanged
            check_unchanged(report['native_products'])
        started=mapping['started_monotonic_ns'];completed=dense_result['completed_monotonic_ns']
        report.update(frame_checks=checked,mapping=mapping,decoder=decode,dense=dense_result,gpu=gpu,
                      hardware_inference_verified=True,
                      timings={'mapping_processing_seconds':mapping['seconds'],
                               'mapping_processing_fps':mapping['fps'],
                               'mapping_with_final_BA_seconds':(native_end-started)*1e-9,
                               'all_geometry_seconds':(completed-started)*1e-9,
                               'all_geometry_fps':len(actual)/((completed-started)*1e-9),
                               'final_GPU_delivery_seconds':(delivered_ns-started)*1e-9})
        from .mapping_acceptance import evaluate
        report.update(evaluate(config.get('acceptance_profile','throughput30'),checked,continuity,report['timings'],
                               profiling=report['profiling'],kernel_tainted=report['kernel_tainted'],last_pose_valid=bool(int(actual[-1]['pose_valid']))))
    except BaseException as error:
        report.update(status='FAILED',error=repr(error));raise
    finally:
        # Every process group belongs to this invocation; never stop other jobs.
        for name,child in reversed(list(children.items())):
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        for log in logs:log.close()
        preview_error=None
        if preview is not None:
            try:
                persisted=preview.close()
                if persisted:report['preview_transport']['persisted_files']=persisted
            except BaseException as error:
                preview_error=error;report.update(status='FAILED',preview_persistence_error=repr(error))
                report.setdefault('error','Preview persistence failed: '+repr(error))
        report['finished_monotonic_ns']=time.monotonic_ns()
        report['available_evidence']={name:load(p) for name,p in {
            'mapping':out/'network_mapping.json','dense':out/'dense/status.json',
            'gui_live':control/'gui_live.json','gpu':control/'gpu.json'}.items() if p.is_file()}
        hashed=('identities','reference_features','executable','model')+(() if uncompressed else ('video',))
        report['file_sha256']={str(path(k)):digest(path(k)) for k in hashed}
        if uncompressed:
            report['raw_source_master_sha256']=packed_source['data_sha256']
            report['raw_integrity']='PC prehashed source; native sealed headers and payload CRC on every frame' if sensor_stream else 'Full local raw-file SHA256 prechecked; native payload CRC on every frame'
        save(control/'RESULT.json',report)
        if preview_error is not None:raise preview_error
    print(json.dumps({'status':report['status'],'timings':report['timings'],'failed_gates':report['failed_gates']}),flush=True)
    return 0 if report['status'] in ('ACTUAL_TWO_BOARD_DPU_GPU_PASS','ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS') else 2


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--frames',type=int,default=0)
    a=p.parse_args();raise SystemExit(run(a.config,a.output,a.frames))
