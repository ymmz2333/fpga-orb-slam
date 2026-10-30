#!/usr/bin/env python3
"""Durable board batch: five round-robin repetitions, stop immediately on thermal cap."""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT=pathlib.Path(__file__).resolve().parent.parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    parser.add_argument('--cooling-note',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.batch):
        raise SystemExit('Invalid batch ID')
    directory=ROOT/'runtime/a3'/args.batch
    directory.mkdir(parents=True,exist_ok=False)
    configs=json.loads((ROOT/'configs/a3/manifest.json').read_text())
    for config in configs:
        if hashlib.sha256((ROOT/config['settings']).read_bytes()).hexdigest()!=config['sha256']:
            raise SystemExit('Config hash mismatch')
    schedule=[dict(config,run_index=run,folder='%s_run%02d'%(config['configuration'],run))
              for run in range(1,6) for config in configs]
    state=dict(status='RUNNING',completed=0,planned=len(schedule),schedule=schedule,
               cooling_note=args.cooling_note,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    def save():
        state['updated_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        target=directory/'batch_state.json'; temp=directory/'batch_state.tmp'
        temp.write_text(json.dumps(state,indent=2,ensure_ascii=False)); temp.replace(target)
    save()
    for item in schedule:
        folder=directory/item['folder']; state['current']=item['folder']; save()
        command=[sys.executable,str(ROOT/'scripts/run_a2.py'),'--output',str(folder),
                 '--settings',str(ROOT/item['settings']),'--cooling-note',args.cooling_note,'--stop-on-frequency-drop']
        with (directory/'batch.log').open('a') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
        metadata=json.loads((folder/'run_metadata.json').read_text()) if (folder/'run_metadata.json').exists() else {}
        item.update(process_status=metadata.get('status','FAILED'),exit_code=metadata.get('exit_code'),
                    runner_exit_code=result.returncode,frequency_drop=metadata.get('frequency_drop_detected',False),
                    thermal_cap=metadata.get('thermal_cap_detected',False))
        state['completed']+=1; save()
        if item['frequency_drop'] or item['thermal_cap']:
            state.update(status='THERMAL_PAUSE',reason='A76 downclock detected; do not start another run or replace affected run'); save()
            return 2
        if not metadata.get('governors_restored',False):
            state.update(status='ERROR_PAUSE',reason='Governor restoration failed or metadata missing'); save()
            return 3
        if metadata.get('status')=='FAILED' and metadata.get('exit_code') is None:
            state.update(status='ERROR_PAUSE',reason=metadata.get('error','Preparation failed')); save()
            return 3
        if result.returncode==0:
            program=(folder/'program.log').read_text(errors='replace')
            if item['tracking_width']==376:
                match=re.search(r'Camera 1 parameters after resize:\s*\[([^]]+)\]',program)
                actual=list(map(float,match.group(1).split())) if match else []
                if len(actual)!=4 or any(abs(a-b)>0.001 for a,b in zip(actual,item['effective_intrinsics'])):
                    state.update(status='ERROR_PAUSE',reason='Settings effective intrinsics do not match expected half-scale'); save()
                    return 3
                item['observed_intrinsics']=actual; save()
        # A SLAM crash or tracking failure is retained, never rerun or replaced.
    state.update(status='FINISHED',current=None); save()
    return 0

if __name__=='__main__':
    raise SystemExit(main())
