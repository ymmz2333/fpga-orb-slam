#!/usr/bin/env python3
"""After the user returns: fetch batch, evaluate on PC, retain raw CSV evidence."""
import argparse
import json
import pathlib
import shutil
import subprocess
import traceback
from analyze_a2 import analyze
from evaluate_a2 import evaluate
from summarize_a3 import summarize

ROOT=pathlib.Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(); parser.add_argument('--batch',required=True)
parser.add_argument('--dataset',required=True); parser.add_argument('--local-only',action='store_true')
args=parser.parse_args()
if not args.batch or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in args.batch):
    raise SystemExit('Invalid batch ID')
source=ROOT/'runtime/a3'/args.batch; source.parent.mkdir(parents=True,exist_ok=True)
if not args.local_only:
    board=json.loads((ROOT/'local_board.json').read_text(encoding='utf-8')); alias=board.get('sshAlias','rk3588')
    remote=board.get('remoteRoot','~/orbslam3_cpu_baseline')
    if any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-' for c in alias) or alias.startswith('-'):
        raise SystemExit('Invalid SSH alias')
    if not remote.startswith(('~/','/')) or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./~' for c in remote):
        raise SystemExit('Invalid remote root')
    subprocess.run(['scp','-q','-r',alias+':'+remote+'/runtime/a3/'+args.batch,str(source.parent)],check=True)
state=json.loads((source/'batch_state.json').read_text(encoding='utf-8'))
if state['status']=='RUNNING':
    raise SystemExit('Batch is still running; no evaluation of incomplete live files')
report=ROOT/'reports/a3'/args.batch; (report/'raw').mkdir(parents=True,exist_ok=True)
shutil.copy2(source/'batch_state.json',report/'batch_state.json')
files=['run_metadata.json','settings.yaml','TrackingStates.csv','TrackingTimeStats.txt','SessionInfo.txt',
       'ExecMean.txt','LocalMapTimeStats.txt','LBA_Stats.txt','program.log','telemetry.csv','f_MH01.txt','kf_MH01.txt',
       'timing_summary.csv','module_summary.csv','timing_facts.json','ate.json','ate.csv','ape.zip','ape_inputs.json',
       'evo.log','evo_command.json','ape_errors.csv','sim3.json','evaluation.json','evaluation.log']
for item in state['schedule']:
    folder=source/item['folder']
    if not (folder/'run_metadata.json').exists(): continue
    meta=json.loads((folder/'run_metadata.json').read_text(encoding='utf-8')); errors=[]
    if meta['status']=='FINISHED':
        try: analyze(folder,expected_frames=3682)
        except Exception as error: errors.append('Timing: '+str(error)); (folder/'evaluation.log').write_text(traceback.format_exc())
        try: evaluate(folder,args.dataset)
        except Exception as error:
            errors.append('ATE: '+str(error))
            with (folder/'evaluation.log').open('a') as stream: stream.write(traceback.format_exc())
    else: errors.append(meta.get('error') or 'SLAM process failed, exit=%s'%meta['exit_code'])
    (folder/'evaluation.json').write_text(json.dumps(dict(status='FAILED' if errors else 'PASS',reason='; '.join(errors)),indent=2))
    target=report/'raw'/item['folder']; target.mkdir(exist_ok=True)
    for name in files:
        if (folder/name).exists(): shutil.copy2(folder/name,target/name)
    for name in ('preflight','dataset_validation'):
        if (folder/name).exists(): shutil.copytree(folder/name,target/name,dirs_exist_ok=True)
summarize(report)
print('A3_EVALUATED batch_status=%s completed=%d/%d report=%s'%(state['status'],state['completed'],state['planned'],report))
