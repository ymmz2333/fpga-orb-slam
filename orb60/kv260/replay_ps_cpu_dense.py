"""Board diagnostic: saved real PL -> native PS mapping/MiDaS/fusion -> Mali GPU.

This deliberately does not claim current KV260 PL execution.
"""
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
from .camera_contract import validate_pair
from .dense_fusion import save
from .frame_store import FrameStore
from .replay_saved import serve


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('board_root','output'):p.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    p.add_argument('--frames',type=int,default=300);p.add_argument('--interval',type=float,default=3)
    p.add_argument('--display-seconds',type=float,default=25);a=p.parse_args()
    if platform.machine()!='aarch64':p.error('Actual KV260 PS test required')
    root=a.board_root.resolve();out=a.output.resolve();inputs=root/'replay_300'
    camera=inputs/'camera_from_yaml_v2.csv';validate_pair(camera,inputs/'camera.yaml')
    out.mkdir(parents=True,exist_ok=False)
    for path in ('dense/color_poses','dense/rgb_cache'):(out/path).mkdir(parents=True)
    config=dict(backend='ps_cpu',model=str(root/'models/midas_ps_cpu_fp32.onnx'),
                model_sha256='8b2c642814a81f56e461d97b73d72d73864be9cee7b59a6fe21cd528ec377ac1',
                camera=str(camera),threads=2,cpu_affinity=[2,3],nice=10,port=18787,
                keyframes_only=True,interval_seconds=a.interval,linger_after_complete=True)
    save(out/'depth_config.json',config)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(180)
    port=listener.getsockname()[1];ready=threading.Event();errors=[];children=[];logs=[]
    store=FrameStore(out/'dense/rgb_cache',capacity=32)
    with (inputs/'capture/frames.csv').open(newline='') as f:source_frames=list(csv.DictReader(f))[:a.frames]
    with (out/'source_frames.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['timestamp_ns','source_frame_index'])
        writer.writerows((int(row['timestamp_ns']),int(row['source_frame_index'])) for row in source_frames)
    def producer():
        try:serve(listener,inputs/'capture',inputs/'video.mp4',camera.read_bytes(),a.frames,ready,store)
        except BaseException as error:errors.append(repr(error));ready.set()
        finally:listener.close()
    thread=threading.Thread(target=producer,daemon=True);thread.start();ready.wait(20)
    def launch(command,label,env=None):
        log=(out/(label+'.log')).open('w');logs.append(log)
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env);children.append(child);return child
    report=dict(status='STARTING',orb_backend='saved_physical_7015_PL',live_kv260_pl=False,
                mapping_backend='KV260_PS',depth_backend='kv260_ps_cpu',cpu_orb_calls=None)
    try:
        if errors:raise RuntimeError(errors)
        depth=launch([sys.executable,'-m','orb60.kv260.dense_service','--config',str(out/'depth_config.json'),
                      '--run',str(out),'--stop-file',str(out/'stop_dense')],'dense')
        env=os.environ.copy();env.update(ORB60_BRIDGE_COLOR_POSES=str(out/'dense/color_poses'),
                 ORB60_KV260_KEYFRAME_DEPTH='1',ORB60_KV260_DEPTH_INTERVAL_NS=str(round(a.interval*1e9)))
        slam=launch([str(root/'build/bin/mono_kv260'),str(root/'vocabulary/ORBvoc.txt'),str(inputs/'camera.yaml'),
                     str(camera),'127.0.0.1',str(port),str(out/'tracking'),str(out/'tracking/telemetry')],'slam',env)
        gui_env=os.environ.copy();gui_env.update(ORB60_GUI_SOURCE_SCOPE='saved_pl_replay',QT_QPA_PLATFORM='xcb',
                QT_OPENGL='es2',QT_XCB_GL_INTEGRATION='xcb_egl',ORB60_GUI_DEPTH_BACKEND='ps_cpu')
        gui=launch([str(root/'.venv_gui/bin/python'),'-m','orb60.kv260.gui','--dense-live','127.0.0.1:18787',
                    '--metrics',str(out/'gpu_display.json'),'--screenshot',str(out/'gpu_snapshot'),
                    '--frame-map',str(out/'source_frames.csv'),'--screenshot-frame',str(a.frames-1),
                    '--exit-after','240'],'gui',gui_env)
        report['status']='RUNNING';save(out/'TEST.json',report)
        while slam.poll() is None:
            if errors:raise RuntimeError(errors)
            if depth.poll() is not None:raise RuntimeError('PS dense process stopped; inspect dense.log')
            if gui.poll() is not None:raise RuntimeError('Actual GPU UI stopped; inspect gui.log')
            time.sleep(.5)
        if slam.returncode:raise RuntimeError('Native PS mapping failed; inspect slam.log')
        thread.join(timeout=10)
        if thread.is_alive() or errors:raise RuntimeError('Saved PL source did not drain: '+str(errors))
        (out/'stop_dense').touch();deadline=time.monotonic()+180
        while True:
            path=out/'dense/status.json';state=json.loads(path.read_text()) if path.exists() else {}
            if state.get('status')=='COMPLETED':break
            if depth.poll() is not None or time.monotonic()>deadline:raise RuntimeError('PS dense finalization failed; inspect dense.log')
            time.sleep(.5)
        # Let the GPU consume final blocks before requesting framebuffer evidence.
        deadline=time.monotonic()+a.display_seconds
        while time.monotonic()<deadline:
            if gui.poll() is not None:raise RuntimeError('GPU viewer stopped before final display')
            time.sleep(.5)
        with (out/'tracking/frames.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        selected=[json.loads(path.read_text()) for path in (out/'dense/color_poses').glob('f*.json')]
        if len(rows)!=a.frames or not selected or any(m.get('anchor_kind')!='slam_keyframe' for m in selected):
            raise RuntimeError('Missing real SLAM keyframes or mapping frames')
        calls=sum(int(row['cpu_orb_calls']) for row in rows)
        if calls or not state['maps'] or any(m['points']<=0 for m in state['maps']):raise RuntimeError('CPU ORB or empty colored output')
        report.update(status='PS_CPU_CHAIN_PASS_GPU_EVIDENCE_PENDING',frames=len(rows),valid_poses=sum(int(r['pose_valid']) for r in rows),
                      cpu_orb_calls=calls,selected_keyframes=len(selected),dense=state)
        save(out/'TEST.json',report)
        print('PS_CPU_CHAIN_DRAINED',json.dumps({k:v for k,v in report.items() if k!='dense'}),flush=True)
        # Keep the useful final result visible; the caller may inspect framebuffer
        # evidence and terminate the owned process after its bounded check.
        while gui.poll() is None:time.sleep(.5)
        (out/'stop_display').touch();depth.wait(timeout=30)
        return 0
    except BaseException as error:
        report.update(status='FAILED',error=repr(error));raise
    finally:
        save(out/'TEST.json',report);(out/'stop_dense').touch();(out/'stop_display').touch()
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()
        for log in logs:log.close()


if __name__=='__main__':raise SystemExit(main())
