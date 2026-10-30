#!/usr/bin/env python3
"""Single bounded startup check; reads compact state once normal tracking is buffered."""
import argparse
import csv
import json
import os
import pathlib
import time
ROOT=pathlib.Path(__file__).resolve().parent.parent
p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); a=p.parse_args()
directory=ROOT/'runtime/b1'/a.batch
for attempt in range(55):
    state_path=directory/'batch_state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        if state['status']!='RUNNING': raise SystemExit('Batch did not start: '+state['status']+' '+state.get('reason',''))
        folder=directory/state['current'] if state.get('current') else None
        if folder and (folder/'run_metadata.json').exists():
            meta=json.loads((folder/'run_metadata.json').read_text())
            if meta['status']=='RUNNING' and (folder/'TrackingStates.csv').exists():
                with (folder/'TrackingStates.csv').open() as f: rows=list(csv.DictReader(f))
                normal=sum(row.get('state_after')=='2' for row in rows)
                if normal:
                    print('B1_STARTED phase=%s first=%s normal_frames_buffered=%d pid=%s affinity=%s start_utc=%s'%
                          (state['phase'],state['current'],normal,meta['slam_pid'],sorted(os.sched_getaffinity(meta['slam_pid'])),meta['start_utc']))
                    print('DMC=%s target_hz=%s actual_hz=%s CPU=%s temperature_mc=%s planned_formal_runs=%s'%
                          (meta['dmc_governor_during'],meta['dmc_target_hz'],meta['before_sensors']['dmc_cur_hz'],
                           meta['governors_during_run'],meta['before_sensors']['thermal_zone0_temp_mc'],state['planned']))
                    raise SystemExit(0)
    time.sleep(1)
raise SystemExit('Startup not confirmed within 55 s; do not claim successful start')
