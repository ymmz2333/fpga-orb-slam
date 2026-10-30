#!/usr/bin/env python3
"""One bounded startup check, no program-log polling or continuous monitoring."""
import argparse
import csv
import json
import os
import pathlib
import time

ROOT=pathlib.Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(); parser.add_argument('--batch',required=True); args=parser.parse_args()
directory=ROOT/'runtime/a3'/args.batch
for attempt in range(60):
    state_path=directory/'batch_state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        if state['status']!='RUNNING': raise SystemExit('Batch did not start: '+state['status'])
        folder=directory/state['current'] if state.get('current') else None
        if folder and (folder/'run_metadata.json').exists():
            meta=json.loads((folder/'run_metadata.json').read_text())
            if meta['status']=='RUNNING' and (folder/'TrackingStates.csv').exists():
                with (folder/'TrackingStates.csv').open() as stream: rows=list(csv.DictReader(stream))
                if any(row.get('state_after')=='2' for row in rows):
                    print('A3_STARTED first=%s normal_tracking=true pid=%s affinity=%s start_utc=%s'%
                          (state['current'],meta['slam_pid'],sorted(os.sched_getaffinity(meta['slam_pid'])),meta['start_utc']))
                    print('governors=%s before_temperature_mc=%s planned_runs=%s'%
                          (meta['governors_during_run'],meta['before_sensors']['thermal_zone0_temp_mc'],state['planned']))
                    raise SystemExit(0)
    time.sleep(1)
raise SystemExit('Startup not confirmed within 60 seconds; investigate before claiming successful start')
