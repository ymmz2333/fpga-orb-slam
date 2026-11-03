"""Diagnostic native 7015->KV260 mapping baseline; no DPU success claim."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(a):
    a.output=a.output.resolve();control=a.output.with_name(a.output.name+'_control')
    if a.output.exists() or control.exists():raise ValueError('Fresh mapping and control directories required')
    control.mkdir(parents=True);fifo=control/'original_bgr.fifo';os.mkfifo(fifo,0o600)
    children=[];logs=[]
    report=dict(status='RUNNING',frontend='actual_zynq7015_PL',mapping='KV260_PS',dpu_used=False,
                scope='Diagnostic mapping baseline; source-video decode and actual network/PL included, no dense inference or GUI')
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','ORB60_VIEWER_FPS':str(a.telemetry_fps),
         'ORB60_KV260_DEPTH_INTERVAL_NS':'3000000000'}
    def start(command,name):
        log=(control/(name+'.log')).open('w');logs.append(log)
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env);children.append(child);return child
    try:
        decode=start([sys.executable,'-m','orb60.kv260.video_pipe','--video',str(a.video.resolve()),'--fifo',str(fifo),
                      '--identities',str(a.identities.resolve()),'--frames',str(a.frames),'--summary',str(control/'decoder.json')],'decoder')
        command=[str(a.executable.resolve()),str(a.vocabulary.resolve()),str(a.yaml.resolve()),'pipe:'+str(fifo),
                 str(a.identities.resolve()),a.endpoint,str(a.output),str(a.frames),'1' if a.telemetry else '0']
        native=start(command,'native');report['command']=command
        while native.poll() is None:
            if decode.poll() is not None and decode.returncode:raise RuntimeError('Original decoder failed; inspect decoder.log')
            time.sleep(.5)
        if native.returncode:raise RuntimeError('Native mapping failed; inspect native.log')
        if decode.wait(timeout=15):raise RuntimeError('Original decoder did not drain normally')
        mapping=json.loads((a.output/'network_mapping.json').read_text())
        decoder=json.loads((control/'decoder.json').read_text())
        with (a.output/'tracking/frames.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        if mapping['frames']!=len(rows) or decoder['frames']!=len(rows) or decoder['status']!='ORIGINAL_VIDEO_FIFO_DRAINED':raise ValueError('Incomplete source/network/mapping drain')
        if any(int(r['cpu_orb_calls']) for r in rows):raise ValueError('CPU ORB fallback forbidden')
        if [int(r['source_frame_id']) for r in rows]!=list(range(len(rows))):raise ValueError('Missing source frame')
        if not (a.output/'NATIVE_COMPLETE').is_file() or not (a.output/'tracking/map/EXPORT_COMPLETE').is_file():raise ValueError('Final native map not complete')
        first=next(i for i,r in enumerate(rows) if int(r['pose_valid']))
        ratio=sum(int(r['pose_valid']) for r in rows[first:])/len(rows[first:])
        report.update(mapping=mapping,decoder=decoder,valid_after_initialization=ratio)
        if ratio<.98:raise ValueError('Tracking stability failed: less than98% valid after initialization')
        report['status']='ACTUAL_7015_KV260_VIDEO_MAPPING_PASS'
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
        for log in logs:log.close()
        report['hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (control/'decoder.json',a.identities,a.executable) if p.is_file()}
        (control/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('video','identities','executable','vocabulary','yaml','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--endpoint',required=True);p.add_argument('--frames',type=int,default=0)
    p.add_argument('--telemetry',action='store_true');p.add_argument('--telemetry-fps',type=int,default=10)
    run(p.parse_args())
