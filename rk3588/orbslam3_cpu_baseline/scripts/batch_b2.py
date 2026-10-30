"""Detached B2 smoke only: original/inject gates, 30 attempts, full Tello FAST probe."""
import argparse,csv,datetime,hashlib,json,pathlib,re,shutil,subprocess,sys,tarfile,time
from prepare_b2 import prepare
from analyze_b2 import analyze
from verify_b2_corpus import verify
ROOT=pathlib.Path(__file__).resolve().parent.parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--cooling-note',required=True);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch ID')
    root=ROOT/'runtime/b2'/a.batch;root.mkdir(parents=True,exist_ok=False)
    manifest=prepare(root/'configs');plan=manifest['plan'];variants=list(plan['variants']);datasets=manifest['datasets']
    schedule=[dict(dataset=d['name'],variant=v,folder=d['name']+'__'+v) for v in variants for d in datasets]
    state=dict(status='RUNNING',phase='smoke',completed=0,planned=len(schedule),current=None,schedule=schedule,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='B2 smoke; B3 not started',
        binary_source_commit=(ROOT/'runtime/b2/original_reference/commit.txt').read_text().strip(),
        producer_source_commit=subprocess.check_output(['git','-C',str(ROOT/'vendor/ORB_SLAM3'),'rev-parse','HEAD'],text=True).strip(),
        producer_sha256=hashlib.sha256((ROOT/'build/b2_candidates/orb_candidates').read_bytes()).hexdigest())
    def save():
        state['updated_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        tmp=root/'batch_state.tmp';tmp.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8');tmp.replace(root/'batch_state.json')
    def command(cmd,name):
        with (root/(name+'.log')).open('wb') as log:return subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL).returncode
    def fail(reason,thermal=False):
        state.update(status='THERMAL_PAUSE' if thermal else 'ERROR_PAUSE',reason=reason);save();print(state['status']+' '+reason,flush=True);return 2
    save()
    try:
        for item in schedule:
            d=next(d for d in datasets if d['name']==item['dataset']);v=item['variant'];state.update(current=item['folder'],phase='smoke');save()
            corpus=root/'corpus'/item['folder']
            if v!='native':
                state['phase']='generate_and_verify';save();corpus.parent.mkdir(exist_ok=True)
                started=time.monotonic()
                code=command([str(ROOT/'build/b2_candidates/orb_candidates'),'--config',d['configs'][v],
                    '--dataset',d['path'],'--timestamps',d['smoke_timestamps'],'--output',str(corpus),'--stride',str(plan['audit_stride'])],item['folder']+'_generate')
                item['generation_wall_s']=time.monotonic()-started
                if code:return fail('Feature generation failed: '+item['folder'])
                item['packet_check']=verify(corpus,d['smoke_timestamps'],d['configs'][v],d['width'],d['height'])
                item['corpus_packet_bytes']=64*(item['packet_check']['files']+item['packet_check']['points'])
                checks=root/'candidate_checks'/item['folder'];checks.mkdir(parents=True)
                for name in ('layers.csv','descriptor_audit.csv','packet_verification.csv','packet_verification.json'):
                    shutil.copy2(corpus/name,checks/name)
                save()
            state['phase']='smoke';save();folder=root/'runs'/item['folder']
            cmd=[sys.executable,str(ROOT/'scripts/run_a2.py'),'--output',str(folder),'--settings',d['configs'][v],
                '--dataset',d['path'],'--dataset-kind',d['kind'],'--timestamps',d['smoke_timestamps'],
                '--sequence','MH01' if d['kind']=='euroc' else d['name'],'--cooling-note',a.cooling_note,
                '--feature-mode','native' if v=='native' else 'inject','--stop-on-frequency-drop','--dmc-performance']
            if v!='native':cmd+=['--feature-dir',str(corpus)]
            code=command(cmd,item['folder']+'_runner')
            meta=json.loads((folder/'run_metadata.json').read_text())
            meta.update(binary_source_commit=state['binary_source_commit'],producer_source_commit=state['producer_source_commit'],
                orb_commit_semantics='working source; accepted SLAM binary was built from binary_source_commit',
                design_label='设计候选',intrinsics_label=d['intrinsics_label'],smoke_prefix_frames=plan['smoke_frames'])
            (folder/'run_metadata.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
            item.update(status=meta['status'],runner_exit=code,wall_time_s=meta.get('wall_time_s'),cpu_drop=meta['frequency_drop_detected'],dmc_drop=meta['dmc_frequency_drop'])
            state['completed']+=1;save()
            if item['cpu_drop'] or item['dmc_drop'] or meta.get('thermal_cap_detected'):return fail('Frequency drop; affected attempt retained',True)
            if not meta.get('governors_restored') or not meta.get('dmc_restored'):return fail('Governor restoration failed')
            if code:
                # A genuine algorithm/process failure stays in the schedule, never replace it.
                item['acceptance']='FAILED_PROCESS';item['error']=meta.get('error','See program.log');save();continue
            facts=analyze(folder,d,v,plan['smoke_frames']);item['facts']=facts
            item['acceptance']='PASS' if facts['initialization_succeeded'] else 'FAILED_INITIALIZATION';save()
            print('B2_SMOKE dataset=%s variant=%s complete=%d initialized=%s losses=%d'%(d['name'],v,facts['processed_frames'],facts['initialization_succeeded'],facts['loss_segments']),flush=True)
        state.update(phase='fast_probe',current=None);save()
        for d in datasets:
            if d['kind']!='prepared':continue
            state['current']=d['name'];save();out=root/'fast_probe'/d['name'];out.parent.mkdir(exist_ok=True)
            code=command([str(ROOT/'build/b2_candidates/orb_candidates'),'--config',d['configs']['V0'],'--dataset',d['path'],
                '--timestamps',d['timestamps'],'--output',str(out),'--probe','1'],d['name']+'_fast_probe')
            if code:return fail('FAST probe failed '+d['name'])
        state.update(phase='packaging',current=None);save()
        # Transport compact raw results, excluding feature corpora and original inputs.
        paths=[p for p in root.rglob('*') if p.is_file() and 'corpus' not in p.relative_to(root).parts and p.name!='batch_state.json']
        with (root/'raw_manifest.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);w.writeheader()
            for path in sorted(paths):w.writerow(dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        with tarfile.open(root/'results.tar.gz','w:gz') as archive:
            for path in paths+[root/'raw_manifest.csv']:archive.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)
        state.update(status='FINISHED',phase='await_pc_report',current=None,
            export_sha256=hashlib.sha256((root/'results.tar.gz').read_bytes()).hexdigest());save()
        print('B2_BATCH_FINISHED: smoke and FAST probes only; B3 awaits approval',flush=True);return 0
    except Exception as error:return fail(str(error))
if __name__=='__main__':raise SystemExit(main())
