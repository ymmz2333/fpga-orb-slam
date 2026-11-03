"""Single KV260: ORB PL -> PS SLAM + explicit CPU/DPU depth -> RGB fusion -> GPU."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import threading
import time
import zlib
import cv2
from .frame_store import FrameStore
from .runtime import XrtWorkspace,UioCore,OrbFrontend
from .dense_fusion import save
from .camera_contract import validate_pair
from .source_frame_map import SourceFrameMap
from orb60.demo_bridge.protocol import Packet,Kind,PROFILE,receive
import hashlib


class VideoSource:
    def __init__(self,path,reuse_converter=False):
        import av
        self.container=av.open(str(path));self.frames=iter(self.container.decode(video=0));self.timestamp_ns=None
        from .video_conversion import BgrConverter
        self.converter=BgrConverter(reuse_converter)
    def read(self):
        try:frame=next(self.frames)
        except StopIteration:return False,None
        if frame.pts is None or frame.time_base is None:raise ValueError('SD video frame has no source timestamp')
        self.timestamp_ns=1000000000+int(frame.pts*frame.time_base*1000000000)
        return True,self.converter.convert(frame)
    def isOpened(self):return True
    def release(self):self.container.close()


def produce(listener,config,root,capture,frontend,stop,errors):
    frame_map=None
    try:
        frame_map=SourceFrameMap(root/'source_frames.csv')
        camera=Path(config['camera']).read_bytes();sha=hashlib.sha256(camera).hexdigest();cache=FrameStore(root/'dense/rgb_cache')
        peer,_=listener.accept()
        with peer:
            peer.settimeout(120);hello=receive(peer)
            if hello.kind!=Kind.HELLO or hello.body.decode()!=sha:raise ValueError('Local SLAM calibration mismatch')
            peer.sendall(Packet(Kind.HELLO,body=(sha+'\n'+PROFILE+'\n').encode()+camera).encode())
            frame=0;next_color=0;previous=0;last=None
            while not stop.is_set():
                if config.get('max_frames') and frame>=config['max_frames']:break
                ok,bgr=capture.read()
                if not ok:break
                if config.get('input_layout')=='center_crop_1280x720':
                    if bgr.shape!=(720,1280,3):raise ValueError('Expected source camera 1280x720')
                    bgr=bgr[:,160:1120].copy()
                if bgr.shape!=(720,960,3):raise ValueError('Expected explicit 960x720 working image; no implicit resize')
                stamp=capture.timestamp_ns if isinstance(capture,VideoSource) else time.monotonic_ns()
                if stamp<=previous:raise ValueError('Source clock did not advance')
                previous=stamp;gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
                frame_map.append(stamp,frame)
                keyframes_only=config['depth'].get('keyframes_only',False)
                color=not keyframes_only and stamp>=next_color
                if color:cache.publish(frame,stamp,bgr,gray);next_color=stamp+500000000
                payload,count=frontend.run(gray)
                packet=Packet(Kind.FRAME,1,frame,stamp,count,zlib.crc32(gray.tobytes()),int(color),gray.tobytes()+payload)
                peer.sendall(packet.encode());ack=receive(peer)
                if (ack.kind,ack.session,ack.frame,ack.stamp)!=(Kind.ACK,1,frame,stamp):raise ValueError('Local PS frame ACK mismatch')
                if keyframes_only:
                    selected=json.loads(ack.body)
                    if selected.get('depth_keyframe_selected'):cache.publish(frame,stamp,bgr,gray)
                last=packet;frame+=1
            if last:
                peer.sendall(Packet(Kind.END,1,last.frame,last.stamp).encode());ack=receive(peer)
                if (ack.kind,ack.frame,ack.stamp)!=(Kind.ACK,last.frame,last.stamp):raise ValueError('Drain mismatch')
    except BaseException as error:errors.append(repr(error));stop.set()
    finally:
        if frame_map:frame_map.close()
        listener.close();capture.release()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    source=p.add_mutually_exclusive_group(required=True);source.add_argument('--camera-device',type=int);source.add_argument('--video',type=Path)
    p.add_argument('--max-frames',type=int,help='Explicit bounded board acceptance run; default consumes the complete input')
    p.add_argument('--no-gui',action='store_true');a=p.parse_args()
    if platform.machine()!='aarch64':p.error('Production system requires KV260 AArch64; no host/CPU ORB fallback')
    config=json.loads(a.config.read_text(encoding='utf-8'));base=a.config.resolve().parent
    if a.max_frames is not None:
        if not 1<=a.max_frames<=100000:p.error('--max-frames must be 1..100000')
        config['max_frames']=a.max_frames
    for key in ('camera','slam_yaml','vocabulary','slam_executable','register_map'):
        config[key]=str((base/config[key]).resolve())
    # Resolving this symlink would turn .venv_gui/bin/python into /usr/bin/python
    # and silently lose the selected virtual environment and its Qt packages.
    if config.get('gui_python'):config['gui_python']=os.path.abspath(base/config['gui_python'])
    depth_backend=config['depth'].get('backend','dpu')
    if depth_backend not in ('dpu','ps_cpu'):p.error('Explicit dpu or ps_cpu depth backend required')
    for key in (('model','placement','preflight','selection') if depth_backend=='dpu' else ('model',)):
        config['depth'][key]=str((base/config['depth'][key]).resolve())
    validate_pair(config['camera'],config['slam_yaml'])
    if any(config['platform'][core].get('address') is None for core in ('layer','descriptor')):p.error('Validated UIO addresses from the selected complete ORB platform are required')
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    for folder in ('dense/color_poses','dense/rgb_cache'):(a.output/folder).mkdir(parents=True,exist_ok=True)
    stop=threading.Event();errors=[];memory=None;cores=[];children=[];logs=[];thread=None;frontend=None
    report={'status':'STARTING','orb_backend':'PL','live_kv260_pl':True,'depth_backend':depth_backend,
            'mapping_backend':'KV260_PS','display_backend':'hardware_GPU_required',
            'source':'SD_video' if a.video else 'camera','max_frames':a.max_frames};gui=None
    try:
        abi=json.loads(Path(config['register_map']).read_text());memory=XrtWorkspace()
        for name in ('layer','descriptor'):
            core=config['platform'][name];cores.append(UioCore(core['uio'],core['name'],int(str(core['address']),0),abi[name]))
        frontend=OrbFrontend(memory,*cores)
        capture=VideoSource(a.video) if a.video else cv2.VideoCapture(a.camera_device)
        if not capture.isOpened():raise RuntimeError('Camera/video source failed')
        if a.video is None:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH,1280 if config.get('input_layout')=='center_crop_1280x720' else 960)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(180);port=listener.getsockname()[1]
        thread=threading.Thread(target=produce,args=(listener,config,a.output,capture,frontend,stop,errors),daemon=True);thread.start()
        config_path=a.output/'depth_config.json';config['depth']['camera']=config['camera'];config['depth']['linger_after_complete']=not a.no_gui;save(config_path,config['depth'])
        def launch(command,label,env=None):
            log=(a.output/(label+'.log')).open('w');logs.append(log)
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env);children.append(child);return child
        depth=launch([sys.executable,'-m','orb60.kv260.dense_service','--config',str(config_path),'--run',str(a.output),'--stop-file',str(a.output/'stop_dense')],'dense')
        env=os.environ.copy();env['ORB60_BRIDGE_COLOR_POSES']=str(a.output/'dense/color_poses')
        if config['depth'].get('keyframes_only'):
            env['ORB60_KV260_KEYFRAME_DEPTH']='1'
            env['ORB60_KV260_DEPTH_INTERVAL_NS']=str(round(config['depth'].get('interval_seconds',3)*1e9))
        slam=launch([config['slam_executable'],config['vocabulary'],config['slam_yaml'],config['camera'],'127.0.0.1',str(port),str(a.output/'tracking'),str(a.output/'tracking/telemetry')],'slam',env)
        if not a.no_gui:
            command=[config.get('gui_python',sys.executable),'-m','orb60.kv260.gui','--dense-live','127.0.0.1:'+str(config['depth'].get('port',18786)),
                        '--frame-map',str(a.output/'source_frames.csv'),'--metrics',str(a.output/'gpu_display.json')]
            if config.get('gui_test_seconds'):
                command+=['--exit-after',str(config['gui_test_seconds']),'--screenshot',str(a.output/'gpu_snapshot')]
                if a.max_frames:command+=['--screenshot-frame',str(a.max_frames-1)]
            gui=launch(command,'gui',
                       {**os.environ,'ORB60_GUI_DEPTH_BACKEND':depth_backend})
        report['status']='RUNNING';save(a.output/'system.json',report)
        while slam.poll() is None:
            if errors:raise RuntimeError(errors)
            if depth.poll() is not None:raise RuntimeError('Dense process stopped; inspect dense.log')
            if gui and gui.poll() is not None:
                if gui.returncode==0:raise KeyboardInterrupt('Viewer closed by user')
                raise RuntimeError('GPU UI stopped; inspect gui.log')
            time.sleep(.5)
        if slam.returncode:raise RuntimeError('PS SLAM failed; inspect slam.log')
        thread.join(timeout=10)
        if thread.is_alive() or errors:raise RuntimeError('Input producer did not drain: '+str(errors))
        with (a.output/'tracking/frames.csv').open(newline='') as f:frames=list(csv.DictReader(f))
        report.update(frames=len(frames),valid_poses=sum(int(row['pose_valid']) for row in frames),
                      cpu_orb_calls=sum(int(row['cpu_orb_calls']) for row in frames))
        if not frames or report['cpu_orb_calls'] or (a.max_frames and len(frames)!=a.max_frames):raise RuntimeError('Actual PL/PS frame count or CPU ORB acceptance failed')
        (a.output/'stop_dense').touch()
        if gui:
            deadline=time.monotonic()+300
            while True:
                status_path=a.output/'dense/status.json'
                state=json.loads(status_path.read_text()) if status_path.exists() else {}
                if state.get('status')=='COMPLETED':break
                if depth.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Dense finalization failed; inspect dense.log')
                time.sleep(.5)
            report['status']='COMPLETED_DISPLAYING';save(a.output/'system.json',report)
            report['dense']=state
            while gui.poll() is None:time.sleep(.5)
            (a.output/'stop_display').touch()
        code=depth.wait(timeout=60)
        if code:raise RuntimeError('Dense drain failed; inspect dense.log')
        report['status']='COMPLETED'
    except KeyboardInterrupt as error:report.update(status='CANCELLED',reason=str(error));return 130
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        stop.set();(a.output/'stop_dense').touch();(a.output/'stop_display').touch()
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()
        for log in logs:log.close()
        if thread:thread.join(timeout=10)
        if cores and frontend and frontend.ever_started:
            while not all(core.read('AP_CTRL')&4 for core in cores):
                report.update(status='HARDWARE_RESET_REQUIRED',error='ORB core remains active; workspace retained until PL reset/idle')
                save(a.output/'system.json',report)
                try:time.sleep(1)
                except KeyboardInterrupt:continue
        for core in cores:core.close()
        if memory:memory.close()
        save(a.output/'system.json',report)


if __name__=='__main__':raise SystemExit(main())
