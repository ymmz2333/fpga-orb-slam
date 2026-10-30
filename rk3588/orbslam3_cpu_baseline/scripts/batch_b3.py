"""Prepared formal round-one runner. Never invoked by B2; explicit user approval required."""
import argparse,datetime,hashlib,json,pathlib,re,shutil,subprocess,sys,time
from prepare_b2 import prepare
from verify_b2_corpus import verify
ROOT=pathlib.Path(__file__).resolve().parent.parent

def schedule(manifest):
    # A new native baseline at the start of every dataset/replicate round.
    return [dict(dataset=d['name'],variant=v,run_index=i,folder=d['name']+'__'+v+'__run%02d'%i)
        for i in range(1,6) for v in manifest['plan']['variants'] for d in manifest['datasets']]

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--cooling-note',required=True)
    p.add_argument('--approved-round-one',action='store_true',help='Only pass after the user accepts B2 and authorizes B3')
    a=p.parse_args()
    if not a.approved_round_one:raise SystemExit('B3 is not authorized by B2. Stop and obtain the user’s explicit B3 approval.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch ID')
    root=ROOT/'runtime/b3'/a.batch;root.mkdir(parents=True,exist_ok=False)
    manifest=prepare(root/'configs');items=schedule(manifest)
    state=dict(status='RUNNING',phase='generate',completed=0,planned=len(items),schedule=items,
        binary_source_commit=(ROOT/'runtime/b2/original_reference/commit.txt').read_text().strip(),
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),forced_loss_implemented=False,
        plan_sha256=manifest['plan_sha256'])
    def save():
        t=root/'state.tmp';t.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8');t.replace(root/'batch_state.json')
    def pause(reason,thermal=False):
        state.update(status='THERMAL_PAUSE' if thermal else 'ERROR_PAUSE',reason=reason);save();return 2
    save()
    # Storage check uses measured B2 packet bytes before this formal runner is approved.
    # Full corpus generation is deterministic and independently checked; no simulated timing is a performance result.
    for d in manifest['datasets']:
        for v in manifest['plan']['variants']:
            if v=='native':continue
            corpus=root/'corpus'/(d['name']+'__'+v);corpus.parent.mkdir(exist_ok=True)
            state.update(current=corpus.name,phase='generate');save()
            if shutil.disk_usage(root).free<2*1024**3:return pause('Less than 2 GiB free; decide storage before continuing')
            cmd=[str(ROOT/'build/b2_candidates/orb_candidates'),'--config',d['configs'][v],'--dataset',d['path'],
                '--timestamps',d['timestamps'],'--output',str(corpus),'--stride',str(manifest['plan']['audit_stride'])]
            with (root/(corpus.name+'_generate.log')).open('wb') as f:result=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
            if result.returncode:return pause('Corpus generation failed '+corpus.name)
            verify(corpus,d['timestamps'],d['configs'][v],d['width'],d['height'])
    state['phase']='formal_round_one';save()
    for item in items:
        d=next(d for d in manifest['datasets'] if d['name']==item['dataset']);v=item['variant'];folder=root/'runs'/item['folder']
        state['current']=item['folder'];save()
        cmd=[sys.executable,str(ROOT/'scripts/run_a2.py'),'--output',str(folder),'--settings',d['configs'][v],
            '--dataset',d['path'],'--dataset-kind',d['kind'],'--timestamps',d['timestamps'],'--sequence',
            'MH01' if d['kind']=='euroc' else d['name'],'--cooling-note',a.cooling_note,'--stop-on-frequency-drop',
            '--dmc-performance','--feature-mode','native' if v=='native' else 'inject']
        if v!='native':cmd+=['--feature-dir',str(root/'corpus'/(d['name']+'__'+v))]
        with (root/(item['folder']+'_runner.log')).open('wb') as f:result=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
        path=folder/'run_metadata.json'
        if not path.exists():return pause('Runner produced no metadata: '+item['folder'])
        meta=json.loads(path.read_text());meta.update(binary_source_commit=state['binary_source_commit'],
            design_label='设计候选',intrinsics_label=d['intrinsics_label'])
        path.write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
        item.update(runner_exit=result.returncode,status=meta['status'],cpu_drop=meta['frequency_drop_detected'],
            dmc_drop=meta.get('dmc_frequency_drop',False),wall_time_s=meta.get('wall_time_s'),error=meta.get('error',''))
        state['completed']+=1;save()
        if item['cpu_drop'] or item['dmc_drop'] or meta['thermal_cap_detected']:return pause('Frequency drop; batch paused; failed result retained',True)
        if not meta.get('governors_restored') or not meta.get('dmc_restored'):return pause('Governor restoration failed')
        # Process/initialization failures are retained, and are not replaced or re-seeded.
        print('B3_ATTEMPT dataset=%s variant=%s run=%d status=%s'%(d['name'],v,item['run_index'],item['status']),flush=True)
    state.update(status='FINISHED',phase='await_pc_evaluation',current=None);save();return 0
if __name__=='__main__':raise SystemExit(main())
