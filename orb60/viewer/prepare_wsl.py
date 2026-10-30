"""Rebuild only the WSL display telemetry; do not install/restart PS firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from probe_wsl import find_project


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    workspace=Path(__file__).resolve().parents[2];project=find_project();root=project/'vendor/ORB_SLAM3'
    a.output.mkdir(parents=True,exist_ok=False);saved={}
    for name in ('include/OrbTelemetry.h','Examples/Monocular/mono_euroc','lib/libORB_SLAM3.so'):
        path=root/name;target=a.output/'before'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target);saved[name]=sha(path)
    header=workspace/'rk3588/orbslam3_cpu_baseline/patches/OrbTelemetry.h'
    state=dict(state='RUNNING',project=str(project),saved_sha256=saved,header_sha256=sha(header))
    def save():(a.output/'status.json').write_text(json.dumps(state,indent=2)+'\n')
    save();shutil.copy2(header,root/'include/OrbTelemetry.h');start=time.monotonic()
    with (a.output/'build.log').open('w') as log:
        run=subprocess.run(['cmake','--build',str(root/'build'),'--target','mono_euroc','--parallel','4'],stdout=log,stderr=subprocess.STDOUT)
    state.update(exit_code=run.returncode,seconds=time.monotonic()-start,state='SUCCEEDED' if run.returncode==0 else 'FAILED')
    if run.returncode==0:state['new_sha256']={name:sha(root/name) for name in saved}
    save();print(json.dumps({key:value for key,value in state.items() if key!='saved_sha256'},indent=2))
    return run.returncode


if __name__=='__main__':raise SystemExit(main())
