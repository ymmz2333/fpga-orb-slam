#!/usr/bin/env python3
"""Background B1: one dual-extractor dump, exact corpus gate, ten interleaved attempts."""
import argparse
import csv
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT=pathlib.Path(__file__).resolve().parent.parent

def main():
    p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); p.add_argument('--cooling-note',required=True)
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch): raise SystemExit('Invalid batch ID')
    directory=ROOT/'runtime/b1'/a.batch; directory.mkdir(parents=True,exist_ok=False)
    corpus=directory/'corpus'; settings=ROOT/'configs/a3/baseline_752x480.yaml'
    schedule=[dict(mode=mode,run_index=run,folder='%s_run%02d'%(mode,run))
              for run in range(1,6) for mode in (('native','inject') if run%2 else ('inject','native'))]
    state=dict(status='RUNNING',phase='dump',completed=0,planned=10,schedule=schedule,
               corpus=str(corpus),cooling_note=a.cooling_note,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    def save():
        state['updated_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        temp=directory/'batch_state.tmp'; temp.write_text(json.dumps(state,indent=2,ensure_ascii=False)); temp.replace(directory/'batch_state.json')
    def pause(reason,thermal=False):
        state.update(status='THERMAL_PAUSE' if thermal else 'ERROR_PAUSE',reason=reason); save(); return 2 if thermal else 3
    def run(item):
        state['current']=item['folder']; save(); folder=directory/item['folder']
        cmd=[sys.executable,str(ROOT/'scripts/run_a2.py'),'--output',str(folder),'--settings',str(settings),
             '--cooling-note',a.cooling_note,'--stop-on-frequency-drop','--dmc-performance','--feature-mode',item['mode']]
        if item['mode']!='native': cmd+=['--feature-dir',str(corpus)]
        with (directory/'batch.log').open('a') as log:
            result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
        metadata=json.loads((folder/'run_metadata.json').read_text()) if (folder/'run_metadata.json').exists() else {}
        item.update(status=metadata.get('status','FAILED'),exit_code=metadata.get('exit_code'),runner_exit=result.returncode,
                    cpu_drop=metadata.get('frequency_drop_detected',False),dmc_drop=metadata.get('dmc_frequency_drop',False),
                    thermal_cap=metadata.get('thermal_cap_detected',False))
        save()
        if item['cpu_drop'] or item['dmc_drop'] or item['thermal_cap']: return pause('CPU/DMC frequency dropped; affected attempt retained',True)
        if not metadata.get('governors_restored') or not metadata.get('dmc_restored'): return pause('CPU/DMC restoration failed or metadata missing')
        if result.returncode: return pause('Attempt failed; inspect bounded log before continuing, never replace result')
        try:
            with (folder/'FeatureTimeStats.csv').open() as f: features=list(csv.DictReader(f))
            with (folder/'TrackingStates.csv').open() as f: states=list(csv.DictReader(f))
        except Exception as error:
            return pause('Per-frame output missing or unreadable: '+str(error))
        if len(features)!=3682 or len(states)!=3682: return pause('Feature/state frame coverage differs from MH01')
        calls={'native':1,'dump':2,'inject':0}[item['mode']]
        if any(int(row['extractor_calls'])!=calls for row in features): return pause('Extractor call-count invariant failed')
        item['processed_frames']=len(states); save(); return 0
    save()
    dump=dict(mode='dump',run_index=0,folder='dump_run00'); state['dump']=dump
    code=run(dump)
    if code: return code
    state.update(phase='verify',current=None); save()
    with (directory/'batch.log').open('a') as log:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/verify_feature_files.py'),'--corpus',str(corpus),
            '--timestamps',str(ROOT/'vendor/ORB_SLAM3/Examples/Monocular/EuRoC_TimeStamps/MH01.txt'),
            '--output',str(directory/'verification')],stdout=log,stderr=subprocess.STDOUT)
    if result.returncode: return pause('Dual-extractor full-frame byte verification failed')
    state['verification']=json.loads((directory/'verification/feature_verification.json').read_text())
    state['phase']='equivalence'; save()
    for item in schedule:
        code=run(item)
        state['completed']+=1; save()
        if code: return code
    state.update(status='FINISHED',phase='await_pc_ate',current=None); save()
    # Preserve a board-authored transport manifest, excluding the multi-GB feature corpus.
    paths=[p for item in [dump]+schedule for p in (directory/item['folder']).rglob('*') if p.is_file()]
    paths += [directory/'batch_state.json']+[p for p in (directory/'verification').glob('*') if p.is_file()]
    with (directory/'raw_manifest.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['path','bytes','sha256']); writer.writeheader()
        for path in sorted(paths):
            writer.writerow(dict(path=str(path.relative_to(directory)),bytes=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    print('B1_BATCH_FINISHED: 10 attempts, waiting for PC ATE and report')
    return 0

if __name__=='__main__': raise SystemExit(main())
