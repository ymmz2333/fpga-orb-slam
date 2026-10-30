"""User-authorized input recovery. Keep failed attempts and append unique recovery runs."""
import argparse,csv,datetime,hashlib,json,pathlib,re,shutil,subprocess,sys,time
from analyze_b2 import analyze
from package_b2 import package
from validate_prepared import validate
from verify_b2_corpus import verify
ROOT=pathlib.Path(__file__).resolve().parent.parent

def select_recoveries(state,root):
    result=[]
    for item in state['schedule']:
        if item.get('recovery_of'):continue
        if item.get('status')=='FAILED':log=root/'runs'/item['folder']/'program.log'
        elif item['folder']==state.get('current') and not item.get('status'):log=root/(item['folder']+'_generate.log')
        else:continue
        if not log.is_file() or b'libpng error: IDAT: CRC error' not in log.read_bytes():continue
        result.append(dict(dataset=item['dataset'],variant=item['variant'],folder=item['folder']+'__input_recovery01',
            recovery_of=item['folder'],recovery_reason='Verified input page-cache corruption; user authorized continuation'))
    return result

def existing_corpus_check(corpus,checks):
    with (checks/'packet_verification.csv').open() as f:rows=list(csv.DictReader(f))
    for row in rows:
        path=corpus/('initialization' if int(row['role']) else 'normal')/(row['timestamp_ns']+'.orb')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Existing feature packet SHA256 mismatch: '+str(path))
    return len(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--cooling-note',required=True);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Invalid batch ID')
    root=ROOT/'runtime/b2'/a.batch;state_path=root/'batch_state.json';state=json.loads(state_path.read_text(encoding='utf-8'))
    if state['status']!='ERROR_PAUSE':raise SystemExit('Recovery requires a stopped input-error batch')
    if hashlib.sha256((ROOT/'build/b2_candidates/orb_candidates').read_bytes()).hexdigest()!=state['producer_sha256']:raise SystemExit('Producer changed; decision required')
    recoveries=select_recoveries(state,root)
    if not recoveries:raise SystemExit('No verified PNG CRC failure selected; algorithm failures are not retried')
    for item in recoveries:
        if (root/'runs'/item['folder']).exists() or (root/'corpus'/item['folder']).exists():raise SystemExit('Recovery output already exists; do not relaunch')
    manifest=json.loads((root/'configs/manifest.json').read_text(encoding='utf-8'));datasets=manifest['datasets'];plan=manifest['plan']
    # Complete hashes outside the timed SLAM section; do not alter source pictures.
    for d in datasets:
        if d['kind']=='prepared':validate(d['path'],full_hash=True)
    shutil.copy2(state_path,root/'batch_state.before_input_recovery.json')
    for item in state['schedule']:
        if any(r['recovery_of']==item['folder'] for r in recoveries) and not item.get('status'):
            item.update(status='FAILED_GENERATION',acceptance='FAILED_GENERATION',error='libpng CRC error; preserved incomplete feature corpus')
    state.update(status='RUNNING',phase='input_recovery',recovery_started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        input_hash_check='PASS for both complete prepared datasets',recovery_folders=[r['folder'] for r in recoveries])
    state.pop('reason',None);state['schedule']+=recoveries;state['planned']=len(state['schedule']);state['completed']=sum('status' in i for i in state['schedule'])
    def save():
        state['updated_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();tmp=root/'state.tmp'
        tmp.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8');tmp.replace(state_path)
    def fail(reason,thermal=False):
        state.update(status='THERMAL_PAUSE' if thermal else 'ERROR_PAUSE',reason=reason);save();print(state['status']+' '+reason,flush=True);return 2
    def command(cmd,name):
        with (root/(name+'.log')).open('wb') as log:return subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL).returncode
    save()
    try:
        for item in recoveries:
            d=next(d for d in datasets if d['name']==item['dataset']);v=item['variant'];state.update(current=item['folder'],phase='input_recovery');save()
            original=next(i for i in state['schedule'] if i['folder']==item['recovery_of']);corpus=root/'corpus'/item['recovery_of']
            checks=root/'candidate_checks'/item['recovery_of'];new_checks=root/'candidate_checks'/item['folder']
            if original.get('packet_check',{}).get('status')=='PASS':
                item['reused_packet_files_verified']=existing_corpus_check(corpus,checks)
                item['packet_check']=original['packet_check'];item['corpus_packet_bytes']=original['corpus_packet_bytes']
                shutil.copytree(checks,new_checks)
            else:
                corpus=root/'corpus'/item['folder'];state['phase']='generate_and_verify';save();started=time.monotonic()
                code=command([str(ROOT/'build/b2_candidates/orb_candidates'),'--config',d['configs'][v],'--dataset',d['path'],
                    '--timestamps',d['smoke_timestamps'],'--output',str(corpus),'--stride',str(plan['audit_stride'])],item['folder']+'_generate')
                item['generation_wall_s']=time.monotonic()-started
                if code:return fail('Recovery feature generation failed; no automatic retry')
                item['packet_check']=verify(corpus,d['smoke_timestamps'],d['configs'][v],d['width'],d['height'])
                item['corpus_packet_bytes']=64*(item['packet_check']['files']+item['packet_check']['points'])
                new_checks.mkdir(parents=True)
                for name in ('layers.csv','descriptor_audit.csv','packet_verification.csv','packet_verification.json'):shutil.copy2(corpus/name,new_checks/name)
            state['phase']='smoke';save();folder=root/'runs'/item['folder']
            cmd=[sys.executable,str(ROOT/'scripts/run_a2.py'),'--output',str(folder),'--settings',d['configs'][v],
                '--dataset',d['path'],'--dataset-kind',d['kind'],'--timestamps',d['smoke_timestamps'],'--sequence',
                'MH01' if d['kind']=='euroc' else d['name'],'--cooling-note',a.cooling_note,'--feature-mode','inject',
                '--feature-dir',str(corpus),'--stop-on-frequency-drop','--dmc-performance']
            code=command(cmd,item['folder']+'_runner');meta=json.loads((folder/'run_metadata.json').read_text(encoding='utf-8'))
            meta.update(binary_source_commit=state['binary_source_commit'],producer_source_commit=state['producer_source_commit'],
                design_label='设计候选',intrinsics_label=d['intrinsics_label'],smoke_prefix_frames=plan['smoke_frames'],recovery_of=item['recovery_of'])
            (folder/'run_metadata.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
            item.update(status=meta['status'],runner_exit=code,wall_time_s=meta.get('wall_time_s'),cpu_drop=meta['frequency_drop_detected'],dmc_drop=meta['dmc_frequency_drop'])
            state['completed']+=1;save()
            if item['cpu_drop'] or item['dmc_drop'] or meta['thermal_cap_detected']:return fail('Frequency drop; recovery paused',True)
            if not meta.get('governors_restored') or not meta.get('dmc_restored'):return fail('Governor restoration failed')
            if code:item.update(acceptance='FAILED_PROCESS',error=meta.get('error','See program.log'));save();continue
            facts=analyze(folder,d,v,plan['smoke_frames']);item.update(facts=facts,acceptance='PASS' if facts['initialization_succeeded'] else 'FAILED_INITIALIZATION');save()
            print('B2_RECOVERY dataset=%s variant=%s initialized=%s frames=%d'%(d['name'],v,facts['initialization_succeeded'],facts['processed_frames']),flush=True)
        state.update(phase='fast_probe',current=None);save()
        for d in datasets:
            if d['kind']!='prepared':continue
            state['current']=d['name'];save();out=root/'fast_probe'/d['name'];out.parent.mkdir(exist_ok=True)
            if out.exists():return fail('FAST output already exists; preserve it and inspect before retry')
            code=command([str(ROOT/'build/b2_candidates/orb_candidates'),'--config',d['configs']['V0'],'--dataset',d['path'],
                '--timestamps',d['timestamps'],'--output',str(out),'--probe','1'],d['name']+'_fast_probe')
            if code:return fail('FAST probe failed '+d['name'])
        state.update(phase='packaging',current=None);save();digest=package(root)
        state.update(status='FINISHED',phase='await_pc_report',current=None,export_sha256=digest);save()
        print('B2_RECOVERY_FINISHED: original failures retained; B3 not started',flush=True);return 0
    except Exception as e:return fail(str(e))
if __name__=='__main__':raise SystemExit(main())
