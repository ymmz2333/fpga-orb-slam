"""Three interleaved attempts per clip, then focal sensitivity on measured stable clip.

No reruns/selective seeds; temperature/frequency gates pause batch and restore governors.
"""
import argparse,datetime,hashlib,json,pathlib,re,subprocess,sys
from analyze_c import analyze_run
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); p.add_argument('--datasets',type=pathlib.Path,required=True)
    p.add_argument('--cooling-note',required=True); a=p.parse_args()
    a.datasets=a.datasets.expanduser().resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch): raise ValueError('Invalid batch ID')
    directory=ROOT/'runtime/c'/a.batch; directory.mkdir(parents=True,exist_ok=False)
    clips=json.loads((a.datasets/'manifest.json').read_text(encoding='utf-8'))['clips']
    schedule=[dict(clip=c['clip'],dataset=c['dataset'],expected_frames=c['expected_frames'],configuration='provisional',run_index=r,
        settings=c['settings'],folder='%s_run%02d'%(c['clip'],r)) for r in range(1,4) for c in clips]
    state=dict(status='RUNNING',phase='baseline',planned=len(schedule),completed=0,schedule=schedule,
        cooling_note=a.cooling_note,intrinsics_label='临时内参，待标定后重跑',
        datasets=str(a.datasets.resolve()),started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    def save():
        temp=directory/'batch_state.tmp'; temp.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8'); temp.replace(directory/'batch_state.json')
    def pause(reason,thermal=False):
        state.update(status='THERMAL_PAUSE' if thermal else 'ERROR_PAUSE',reason=reason); save(); return 2 if thermal else 3
    def run(item):
        state['current']=item['folder']; save(); output=directory/item['folder']; dataset=a.datasets/item['dataset']
        cmd=[sys.executable,str(ROOT/'scripts/run_a2.py'),'--output',str(output),'--settings',str(ROOT/item['settings']),
            '--dataset',str(dataset),'--timestamps',str(dataset/'timestamps.txt'),'--sequence','C',
            '--dataset-kind','prepared','--feature-mode','native','--dmc-performance','--stop-on-frequency-drop','--cooling-note',a.cooling_note]
        with (directory/'batch.log').open('a') as log: code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL).returncode
        meta=json.loads((output/'run_metadata.json').read_text()) if (output/'run_metadata.json').exists() else {}
        item.update(status=meta.get('status','FAILED'),runner_exit=code,exit_code=meta.get('exit_code'),
            cpu_drop=meta.get('frequency_drop_detected',False),dmc_drop=meta.get('dmc_frequency_drop',False),thermal_cap=meta.get('thermal_cap_detected',False))
        state['completed']+=1; save()
        if item['cpu_drop'] or item['dmc_drop'] or item['thermal_cap']: return pause('CPU/DMC downclock; affected attempt retained; no replacement',True)
        if not meta.get('governors_restored') or not meta.get('dmc_restored'): return pause('Governor restoration failed/missing')
        if meta.get('status')=='FAILED' and meta.get('exit_code') is None: return pause(meta.get('error','Preparation failed'))
        if code!=0:
            states=output/'TrackingStates.csv'
            if not states.exists() or len(states.read_text().splitlines())<=1:
                return pause('SLAM exited before recording a frame; inspect input/configuration before more attempts')
        if code==0:
            try: item['facts']=analyze_run(output,item['expected_frames'])
            except Exception as e: return pause('Diagnostics failed: '+str(e))
        else: item['reason']=meta.get('error','SLAM process failed; attempt retained')
        save(); return 0
    save()
    for item in schedule:
        code=run(item)
        if code: return code
    # Choose across all three baseline attempts, not the best individual random outcome.
    candidates=[]
    for clip in clips:
        attempts=[s for s in schedule if s['clip']==clip['clip']]
        if all(s.get('facts',{}).get('initialization_succeeded') for s in attempts):
            candidates.append((min(s['facts']['state_ok_fraction'] for s in attempts),
                -sum(s['facts']['loss_segments'] for s in attempts),clip['clip']))
    if candidates:
        selected=max(candidates)[2]; state['sensitivity_clip']=selected; state['selection_rule']='max minimum OK fraction across 3 attempts, then fewest losses, then clip ID'
        clip=next(c for c in clips if c['clip']==selected)
        extra=[dict(clip=selected,dataset=clip['dataset'],expected_frames=clip['expected_frames'],configuration='focal_'+factor,run_index=r,
            settings='configs/c/tello_oafd_focal_'+factor+'_provisional.yaml',folder='sensitivity_'+factor+'_run%02d'%r)
            for r in range(1,4) for factor in ('09','11')]
        state['phase']='sensitivity'; state['schedule'].extend(extra); state['planned']+=len(extra); save()
        for item in extra:
            code=run(item)
            if code: return code
    else: state['sensitivity_status']='未完成：无全部三次都初始化成功的片段；没有挑选单次成功结果'
    state.update(status='FINISHED',phase='await_pc_report',current=None); save()
    with (directory/'raw_manifest.csv').open('w',newline='') as f:
        import csv
        w=csv.DictWriter(f,fieldnames=['path','bytes','sha256']); w.writeheader()
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.name!='raw_manifest.csv':
                w.writerow(dict(path=str(path.relative_to(directory)),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    print('C_BATCH_FINISHED completed=%d; waiting for PC report'%state['completed']); return 0
if __name__=='__main__': raise SystemExit(main())
