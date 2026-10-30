"""Local WSL -> physical FPGA -> SLAM -> loopback desktop telemetry session."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from bridge import Bridge
from probe_wsl import find_project,find_fpga


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frames',type=int,default=0);p.add_argument('--port',type=int,default=18767)
    p.add_argument('--unpaced',action='store_true');p.add_argument('--record',action='store_true')
    p.add_argument('--linger',action='store_true');a=p.parse_args()
    workspace=Path(__file__).resolve().parents[2];project=find_project();host,interface=find_fpga()
    a.output.mkdir(parents=True,exist_ok=False)
    native=project/'runtime/orb60_desktop'/a.output.name;native.mkdir(parents=True,exist_ok=False)
    dataset=project/'runtime/pc/datasets/flight_20261004T184929_998838_6bb93c56'
    camera=project/'configs/c/tello_oafd_960x720_provisional.yaml'
    assert dataset.is_dir() and camera.is_file()
    shutil.copy2(dataset/'frames.csv',a.output/'source_frames.csv')
    run=native/'slam';bridge=Bridge(run/'telemetry','127.0.0.1',a.port)
    thread=threading.Thread(target=bridge.serve,daemon=True);thread.start()
    state=dict(state='STARTING',project=str(project),host=host,interface=interface,port=a.port,
               run=str(run),display_fps_limit=60,input='recorded video streamed at its timestamps',
               started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    def save():
        temp=a.output/'session.json.tmp';temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(a.output/'session.json')
    save();print(json.dumps(state),flush=True)
    cmd=[sys.executable,str(workspace/'orb60/scripts/run_slam_network.py'),
         '--slam-root',str(project/'vendor/ORB_SLAM3'),'--dataset',str(dataset),'--camera',str(camera),
         '--host',host,'--interface',interface,'--frames',str(a.frames),'--platform','pc',
         '--feature-mode','fpga-pipeline','--telemetry-record' if a.record else '--telemetry',
         '--telemetry-fps','60','--output',str(run)]
    if a.unpaced:cmd.append('--unpaced')
    stopped=threading.Event()
    with (a.output/'runner.log').open('w') as log:
        child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            state['state']='RUNNING';save()
            while child.poll() is None:
                if (a.output/'stop').exists():
                    stopped.set();os.killpg(child.pid,signal.SIGTERM);break
                time.sleep(.2)
            code=child.wait(timeout=10)
            for name in ('status.json','FeatureTimeStats.csv','TrackingStates.csv','output.log','CameraTrajectory.txt'):
                if (run/name).is_file():shutil.copy2(run/name,a.output/name)
            if a.record and (run/'telemetry').is_dir():shutil.copytree(run/'telemetry',a.output/'telemetry')
            state.update(state='CANCELLED' if stopped.is_set() else ('COMPLETED' if code==0 else 'FAILED'),exit_code=code)
            save();print(json.dumps(state),flush=True)
            while a.linger and not (a.output/'stop').exists():time.sleep(.2)
            return 0 if stopped.is_set() else code
        finally:
            if child.poll() is None:os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10)
            bridge.stop.set();thread.join(timeout=3)


if __name__=='__main__':raise SystemExit(main())
