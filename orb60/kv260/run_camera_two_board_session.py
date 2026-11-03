"""KV260 USB camera -> physical7015 ORB -> KV260 PS/DPU/Mali ->7015 localization.

The map is handed off only after real motion, one stable map, actual selected-
keyframe DPU execution and final colored geometry pass the camera gates. A
stationary no-map run ends explicitly before transfer. No hardware is loaded.
"""
import argparse
import json
from pathlib import Path
import platform
import re
import sys
import time
from types import SimpleNamespace
from .run_network_system import load,save,digest
from .two_board_session import Board,network_snapshot


def run(config_path,connection_path,library,output,frames=600,localization_frames=600,resume_mapping=None):
    if platform.machine()!='aarch64' or sys.platform!='linux':raise ValueError('Run this session on actual KV260')
    config_path,connection_path,library,output=map(lambda p:Path(p).resolve(),(config_path,connection_path,library,output))
    if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',output.name) or not 2<=frames<=36000 or not 1<=localization_frames<=36000:
        raise ValueError('Bounded session name and finite camera frame limits required')
    config=load(config_path);connection=load(connection_path);root=Path(config['root']).resolve()
    if not library.is_file():raise ValueError('Actual V4L2 capture library missing')
    def path(key):
        p=Path(config[key]);return p if p.is_absolute() else root/p
    output.mkdir(parents=True,exist_ok=False)
    state=dict(status='RUNNING',mode='LIVE_CAMERA_COMPLETE_CHAIN' if resume_mapping is None else 'CAMERA_HANDOFF_LOCALIZATION_COMPONENT',
               input='actual_KV260_USB3_camera',frontend='actual7015_PL',mapping='KV260_PS',depth='actual_KV260_DPU',
               computer_visual_compute=False,physical_direct_cable_verified=False,stages={},
               mapping_frames_requested=frames,localization_frames_requested=localization_frames,
               source_sha256=digest(__file__),config_sha256=digest(config_path),connection_sha256=digest(connection_path),
               camera_library_sha256=digest(library),started_monotonic_ns=time.monotonic_ns())
    save(output/'session.json',state)
    (output/'mapping_config.json').write_bytes(config_path.read_bytes())
    (output/'connection_config.json').write_bytes(connection_path.read_bytes())
    try:
        network_snapshot(output/'network_before.json')
        mapping=Path(resume_mapping).resolve() if resume_mapping else output/'mapping'
        if resume_mapping is None:
            from .run_camera_system import run as camera_system
            print('开始真实摄像头建图、DPU彩色点云与Mali显示。',flush=True)
            code=camera_system(config_path,mapping,frames)
            result=load(mapping.with_name(mapping.name+'_control')/'RESULT.json')
            state['stages']['mapping']=dict(status=result['status'],run=str(mapping),result_sha256=digest(mapping.with_name(mapping.name+'_control')/'RESULT.json'))
            if result['status']=='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED':
                state['status']='CAMERA_INPUT_COMPLETE_NO_MAP_NO_HANDOFF'
                print('本轮没有初始化地图；已结束采集，不传地图、不启动定位。',flush=True)
                return 2
            if code or result['status']!='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS':raise ValueError('Camera mapping did not pass; no handoff')
        from .handoff_camera_7015 import create
        print('校验并封装同一相机的稀疏地图和彩色环境。',flush=True)
        handoff=output/'handoff';sealed=create(mapping,path('camera'),handoff)
        state['stages']['mapping_source']=sealed['source'];save(output/'session.json',state)
        board=Board(root,connection,output)
        from .install_camera_map_7015 import install
        release='/opt/orb-demo/kv260_network_camera_session_'+output.name
        print('传输地图，并在7015执行原生导入和往返校验。',flush=True)
        installed=install(board,handoff,release,'live_camera')
        state['stages']['native_import']=installed;save(output/'session.json',state)
        from .run_7015_network_localization import run as localize
        print('7015开始PL ORB、PS固定地图定位与彩色背景HDMI。',flush=True)
        target=output/'localization'
        localize(SimpleNamespace(root=root,connection=connection_path,camera=path('camera'),output=target,
                 release=installed['release'],endpoint='['+connection['host']+']:5605',mode='live_camera',frames=localization_frames,
                 fixture=None,baseline_run=None,library=library,source_camera=path('source_camera'),
                 device=config['device'],allow_unmapped_input_probe=False))
        localized=load(target/'RESULT.json')
        if (localized['status']!='ACTUAL_7015_NATIVE_NETWORK_COLOR_LOCALIZATION_COMPONENT_PASS' or
            localized['hardware']['map_version']!=installed['version'] or localized['calibration_sha256']!=installed['calibration_sha256']):
            raise ValueError('7015 localized against another map/camera')
        native_stdout=(target/'native/stdout.log').read_text()
        if 'DENSE_ENVIRONMENT_POINTS='+str(installed['dense_points']) not in native_stdout:
            raise ValueError('7015 HDMI did not load the transferred colored environment')
        state['stages']['localization']=localized
        state['status']=('ACTUAL_KV260_CAMERA_MAPPING_HANDOFF_7015_LOCALIZATION_PASS' if resume_mapping is None
                         else 'ACTUAL_CAMERA_MAP_HANDOFF_LOCALIZATION_COMPONENT_PASS')
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:
        try:network_snapshot(output/'network_after.json')
        except Exception as error:state['network_evidence_error']=repr(error)
        state['finished_monotonic_ns']=time.monotonic_ns();save(output/'session.json',state)
    print(json.dumps(dict(status=state['status'],output=str(output)),ensure_ascii=False),flush=True)
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name,dest in (('config','config_path'),('connection','connection_path'),('library','library'),('output','output')):
        p.add_argument('--'+name,dest=dest,type=Path,required=True)
    p.add_argument('--frames',type=int,default=600);p.add_argument('--localization-frames',type=int,default=600)
    p.add_argument('--resume-mapping',type=Path,help='Explicit accepted camera handoff component; no new mapping claimed')
    return run(**vars(p.parse_args(argv)))


if __name__=='__main__':raise SystemExit(main())
