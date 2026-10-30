#!/usr/bin/env python3
"""Independent NumPy timing/telemetry checks and CSV-only reproducibility."""
import argparse
import csv
import hashlib
import json
import pathlib
import numpy as np
from summarize_a3 import summarize_csv

parser=argparse.ArgumentParser(); parser.add_argument('report',type=pathlib.Path); args=parser.parse_args()
report=args.report
with (report/'results_exp1.csv').open(encoding='utf-8') as stream: rows=list(csv.DictReader(stream))
checks=[]
for row in rows:
    if row['stage']!='A3': continue
    folder=report/'raw'/row['folder']
    with (folder/'TrackingStates.csv').open() as stream: states=list(csv.DictReader(stream))
    timing=np.loadtxt(folder/'TrackingTimeStats.txt',delimiter=',',comments='#')
    normal=np.array([int(s['state_before']) in (2,3,4) and int(s['state_after'])==2 for s in states])
    assert len(states)==len(timing)==3682 and normal.sum()==int(row['frames'])
    total,orb=timing[normal,8],timing[normal,2]
    expected=dict(total_mean_ms=np.mean(total),total_median_ms=np.median(total),total_p95_ms=np.percentile(total,95),
                  orb_median_ms=np.median(orb),orb_p95_ms=np.percentile(orb,95),
                  orb_ratio_frame_median=np.median(orb/total),orb_ratio_sums=np.sum(orb)/np.sum(total),
                  total_gt50_fraction=np.mean(total>50),total_gt33_fraction=np.mean(total>33))
    for name,value in expected.items():
        assert np.isclose(float(row[name]),value,rtol=1e-10,atol=1e-10),(row['folder'],name)
    with (folder/'telemetry.csv').open() as stream: samples=list(csv.DictReader(stream))
    for policy in ('policy4','policy6'):
        assert all(int(s[policy+'_cur_khz'])==2256000 and int(s[policy+'_max_khz'])==2256000 for s in samples)
    assert np.isclose(float(row['mean_soc_temp_c']),np.mean([int(s['thermal_zone0_temp_mc'])/1000 for s in samples]))
    decision=json.loads((folder/'preflight/decision.json').read_text(encoding='utf-8'))
    assert decision['linkage_pass']
    checks.append([row['folder']+' independent timing/frequency/linkage','PASS'])
before=(report/'summary.csv').read_bytes()
summarize_csv(report)
assert before==(report/'summary.csv').read_bytes(),'CSV-only summary is not reproducible'
checks.append(['CSV-only summary byte equality','PASS'])
with (report/'validation.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.writer(stream); writer.writerow(['check','status']); writer.writerows(checks)
manifest={str(p.relative_to(report)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in (report/'raw').rglob('*') if p.is_file()}
(report/'raw_sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('A3_VALIDATION_PASS independent_runs=%d csv_rebuild_exact=true raw_files=%d'%(len(checks)-1,len(manifest)))
