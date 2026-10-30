#!/usr/bin/env python3
"""A1 deterministic input checks all modes and raw alignment, never an experiment."""
import csv
import json
import os
import pathlib
import subprocess
import sys
import time
from analyze_a2 import analyze
ROOT=pathlib.Path(__file__).resolve().parent.parent
out=ROOT/'runtime/b1'/('synthetic_%s_%s'%(time.strftime('%Y%m%dT%H%M%S'),os.getpid()))
out.mkdir(parents=True,exist_ok=False)
env=os.environ.copy(); env.pop('DISPLAY',None); env['LD_LIBRARY_PATH']=str(ROOT/'install/lib')
source=ROOT/'vendor/ORB_SLAM3'; corpus=out/'corpus'; inp=ROOT/'runtime/smoke_input'
subprocess.run([sys.executable,str(ROOT/'scripts/make_smoke_sequence.py')],check=True)
rows=[]
for mode in ('native','dump','inject'):
    folder=out/mode; folder.mkdir()
    cmd=[str(source/'Examples/Monocular/mono_euroc'),str(source/'Vocabulary/ORBvoc.txt'),
         str(inp/'smoke.yaml'),str(inp),str(inp/'timestamps.txt'),'smoke','--no-viewer','--feature-mode',mode]
    if mode!='native': cmd+=['--feature-dir',str(corpus)]
    with (folder/'program.log').open('wb') as log:
        subprocess.run(cmd,cwd=str(folder),env=env,stdout=log,stderr=log,check=True,timeout=120)
    facts=analyze(folder,expected_frames=24)
    with (folder/'FeatureTimeStats.csv').open() as f: features=list(csv.DictReader(f))
    expected=[int(t) for t in (inp/'timestamps.txt').read_text().splitlines()]
    if len(features)!=24 or [int(r['timestamp_ns']) for r in features]!=expected:
        raise RuntimeError('Synthetic feature alignment failed')
    if any(int(r['extractor_calls'])!={'native':1,'dump':2,'inject':0}[mode] for r in features):
        raise RuntimeError('Unexpected extractor calls')
    rows.append(dict(mode=mode,status='PASS',processed_frames=24,extractor_calls_per_frame=features[0]['extractor_calls'],
                     synthetic_only=True))
    if mode=='dump':
        subprocess.run([sys.executable,str(ROOT/'scripts/verify_feature_files.py'),'--synthetic','--corpus',str(corpus),
            '--timestamps',str(inp/'timestamps.txt'),'--output',str(out/'verification')],check=True)
with (out/'verification.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print('B1_SYNTHETIC_PASS native/dump/inject=24frames_each dump=48byte_equal_files; not accuracy/performance data; output='+str(out))
