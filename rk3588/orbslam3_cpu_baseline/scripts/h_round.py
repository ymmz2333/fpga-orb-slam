"""H1/H2 authorized 90-slot PC round. Freeze, diagnose, record failures, stop."""
import argparse,copy,csv,datetime,fcntl,hashlib,json,os,pathlib,re,shutil,subprocess,sys,time
from golden_audit_support import atomic_json,canonical_timestamps,classify,packet,read_rows,write_timestamps
from run_pc_slam import library_environment,verify_linkage,allow_diagnostic_ptrace,capture
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1];GOLDEN=PROJECT/'orb_frontend_golden'
OLD=GOLDEN/'decision/G1_layers_resume_20261006_013559'
BINARY=PROJECT/'.work/golden_h1/fixed_v1/slam_source/Examples/Monocular/mono_euroc'
VOCABULARY=PROJECT/'.work/golden/slam_source/Vocabulary/ORBvoc.txt'
VARIANTS=['native','V0','L8','L4','L8_T2','L4_T2']
def sha(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def topology():
    text=subprocess.check_output(['lscpu','-p=CPU,CORE,SOCKET'],text=True);groups=set();cpus=[]
    for line in text.splitlines():
        if line.startswith('#'):continue
        cpu,core,socket=map(int,line.split(','))
        if cpu in os.sched_getaffinity(0) and (core,socket) not in groups:cpus.append(cpu);groups.add((core,socket))
    if len(cpus)<4:raise ValueError('Four distinct physical core representatives required')
    return cpus[:4],text
def schedule(datasets):
    slots=[]
    for phase,variants in [('H1',['native','V0']),('H2',['L8','L4','L8_T2','L4_T2'])]:
        for repeat in range(1,6):
            order=variants[(repeat-1)%len(variants):]+variants[:(repeat-1)%len(variants)]
            ds=datasets[(repeat-1)%3:]+datasets[:(repeat-1)%3]
            for v in order:
                for d in ds:slots.append(dict(phase=phase,dataset=d['name'],variant=v,run_index=repeat,folder=d['name']+'__'+v+'__run%02d'%repeat,status='PENDING'))
    assert len(slots)==90 and len({r['folder'] for r in slots})==90
    return slots
def prepare(batch):
    out=GOLDEN/'decision'/batch;out.mkdir(exist_ok=False);source=out/'source';source.mkdir()
    fixed=GOLDEN/'decision/H1_fixed_probe_20261006_01/fixed_acceptance.json'
    validation=PROJECT/'.work/golden_h2/validation_01/acceptance.json'
    preflight=GOLDEN/'decision/H1_H2_small_launch_checks_20261006_01/acceptance.json'
    if any(json.loads(p.read_text())['status']!='PASSED' for p in [fixed,validation,preflight]):raise ValueError('H1/T2/launch acceptance missing')
    for name in ['run_pc_slam.py','golden_audit_support.py','golden_report_audited.py','analyze_a2.py','analyze_c.py','evaluate_a2.py','finish_c.py','h_round_report.py']:
        shutil.copy2(ROOT/'scripts'/name,source/name)
    shutil.copy2(PROJECT/'.work/golden_h2/build/orb_golden_cli',source/'orb_golden_cli')
    shutil.copy2(fixed,out/'fixed_acceptance.json');shutil.copy2(validation,out/'T2_acceptance.json')
    shutil.copy2(preflight,out/'launch_acceptance.json')
    shutil.copy2(GOLDEN/'decision/H1_counter_probe_20261006_01/diagnosis.json',out/'diagnosis.json')
    dependencies={str(p):sha(p) for p in source.iterdir()};datasets=[]
    old=json.loads((OLD/'configs/manifest.json').read_text())
    for ds0 in old['datasets']:
        ds=copy.deepcopy(ds0);folder=out/'configs'/ds['name'];folder.mkdir(parents=True);stamps=folder/'timestamps.txt'
        ns=write_timestamps(ds0['timestamps'],stamps);assert len(ns)==ds['full_frames'];ds['timestamps']=str(stamps);ds['configs']={};ds['feature_roots']={}
        for v in VARIANTS:
            template=v.split('_')[0];path=folder/(v+'.yaml');shutil.copy2(ds0['configs'][template],path);ds['configs'][v]=str(path)
            if v!='native':ds['feature_roots'][v]=str((out/'corpus'/ds['name'] if '_T2' in v else pathlib.Path(ds['corpus']))/v)
        records=read_rows(pathlib.Path(ds['corpus'])/'manifest.csv')
        for v in ['V0','L8','L4']:
            expected={v+'/'+role+'/'+str(t)+'.orb' for role in ['normal','initialization'] for t in ns}
            selected=[r for r in records if r['path'].startswith(v+'/')]
            if {r['path'] for r in selected}!=expected:raise ValueError('Incomplete old corpus '+v)
        datasets.append(ds)
        for p in folder.iterdir():dependencies[str(p)]=sha(p)
        for p in [pathlib.Path(ds['input_hashes']),pathlib.Path(ds['corpus'])/'manifest.csv',pathlib.Path(ds['corpus'])/'codec.log']:dependencies[str(p)]=sha(p)
    cpus,text=topology();(out/'topology.txt').write_text(text)
    manifest=dict(datasets=datasets,plan=dict(variants=VARIANTS,scaleFactor=1.2,normal=1000,initialization=5000,rounds=5))
    atomic_json(out/'configs/manifest.json',manifest);dependencies[str(out/'configs/manifest.json')]=sha(out/'configs/manifest.json')
    env,prefix=library_environment(BINARY);ldd=verify_linkage(BINARY,env,prefix)
    if str(BINARY.parents[2]/'lib/libORB_SLAM3.so') not in ldd:raise ValueError('Fixed SLAM library is not selected')
    (out/'linkage.ldd.txt').write_text(ldd)
    for p in [BINARY,VOCABULARY,BINARY.parents[2]/'build_manifest.json',fixed,validation,preflight,PROJECT/'.work/golden_h2/native_counts/native_selected_counts',ROOT/'scripts/historical_selected.py',ROOT/'scripts/h_round.py',GOLDEN/'DESIGN_SPEC_v0.95.md']:
        dependencies[str(p)]=sha(p)
    for path in re.findall(r'=>\s+(/\S+)',ldd):dependencies[path]=sha(pathlib.Path(path))
    probe=GOLDEN/'decision/G1_audit_20261005_02/packet_probe/golden_packet_probe'
    dependencies[str(probe)]=sha(probe)
    if shutil.disk_usage(PROJECT).free<12*(1<<30):raise ValueError('Less than conservative 12 GiB batch reserve')
    state=dict(status='PREPARED',phase='prepared',planned=90,completed=0,failed_slots=0,schedule=schedule(datasets),cores=cpus,
        platform='x86 PC / WSL2',report_title='H1控制流修复与H2双阈值决策轮',forced_loss=False,performance_conclusions=False,
        no_failure_replacement=True,v0_semantics='G1 simplifications-off integer control; not original float byte-equivalent V0',
        frozen_runtime_sha256=dependencies,golden_sha256=sha(source/'orb_golden_cli'),slam_sha256=sha(BINARY),library_sha256=sha(BINARY.parents[2]/'lib/libORB_SLAM3.so'),
        disk_free_bytes=shutil.disk_usage(PROJECT).free,disk_reserve_bytes=12*(1<<30),started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    state['experiment_git_commit']=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    state['golden_git_commit']=subprocess.check_output(['git','-C',str(GOLDEN),'rev-parse','HEAD'],text=True).strip()
    atomic_json(out/'batch_state.json',state);print('H_ROUND_PREPARED',batch,flush=True)
def execute(batch):
    out=GOLDEN/'decision'/batch;state=json.loads((out/'batch_state.json').read_text())
    if state['status']!='PREPARED':raise ValueError('Only a prepared, never-started batch may launch')
    def save():atomic_json(out/'batch_state.json',state)
    def frozen():
        for path,digest in state['frozen_runtime_sha256'].items():
            if sha(path)!=digest:raise ValueError('Frozen dependency changed: '+path)
    def images(d,pgms=False):
        for r in json.loads(pathlib.Path(d['input_hashes']).read_text()):
            p=pathlib.Path(d['path'])/'mav0/cam0/data'/(str(r['timestamp_ns'])+'.png')
            if sha(p)!=r['source_sha256']:raise ValueError('Original PNG changed '+str(p))
            if pgms:
                p=pathlib.Path(d['input_hashes']).parent/(str(r['timestamp_ns'])+'.pgm')
                if sha(p)!=r['pgm_sha256']:raise ValueError('Prepared PGM changed '+str(p))
    def generate(command,path):
        with path.open('w') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=allow_diagnostic_ptrace)
            frames=0;started=updated=time.monotonic()
            while child.poll() is None:
                time.sleep(5)
                with path.open('rb') as f:f.seek(max(0,path.stat().st_size-8192));tail=f.read().decode(errors='replace')
                values=re.findall(r'GOLDEN_SEQUENCE_PROGRESS frames=(\d+)',tail)
                if values and int(values[-1])>frames:frames=int(values[-1]);updated=time.monotonic();state['generated_frames']=frames;save()
                if time.monotonic()-updated>120 or time.monotonic()-started>7200:
                    snapshot=out/(path.stem+'_hang');snapshot.mkdir();atomic_json(snapshot/'capture.json',capture(child.pid,snapshot))
                    child.terminate()
                    try:child.wait(timeout=15)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    raise RuntimeError('Feature generation progress watchdog expired: '+state['current'])
            if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
    try:
        lock=(out.parent/'decision.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        datasets=json.loads((out/'configs/manifest.json').read_text())['datasets'];source=out/'source';frozen();state.update(status='RUNNING',phase='decision_runs');save()
        prepared_h2=False
        for item in state['schedule']:
            if item['phase']=='H2' and not prepared_h2:
                state.update(phase='historical_selected',current=None);save()
                # G1 statistics precede the H2 matrix; native reconstruction is explicitly labeled.
                with (out/'historical_selected.log').open('w') as log:subprocess.run([sys.executable,str(ROOT/'scripts/historical_selected.py'),'--output',str(out/'historical_selected')],stdout=log,stderr=subprocess.STDOUT,check=True)
                state.update(phase='generate_t2_corpus');save()
                probe=GOLDEN/'decision/G1_audit_20261005_02/packet_probe/golden_packet_probe';env,prefix=library_environment(BINARY)
                for d in datasets:
                    frozen();images(d,True);corpus=out/'corpus'/d['name'];corpus.mkdir(parents=True)
                    state.update(current=d['name']);save()
                    command=[str(source/'orb_golden_cli'),'--input',str(pathlib.Path(d['input_hashes']).parent),'--sequence',d['timestamps'],'--output',str(corpus),'--profiles','L8_T2,L4_T2','--stats',str(corpus/'stats.csv')]
                    state['generated_frames']=0;save();generate(command,out/(d['name']+'_generate_t2.log'))
                    rows=[];codec=[];stats={(r['variant'],r['role'],r['timestamp_ns'],r['level']):int(r['selected']) for r in read_rows(corpus/'stats.csv')}
                    for v in ['L8_T2','L4_T2']:
                        levels=int(v[1])
                        for role,name,budget in [(0,'normal',1000),(1,'initialization',5000)]:
                            for ns in canonical_timestamps(d['timestamps'])[0]:
                                p=corpus/v/name/(str(ns)+'.orb');data=p.read_bytes();count=packet(data,ns,role,d['width'],d['height'],levels,budget)
                                if count>budget:raise ValueError('Feature budget exceeded')
                                import collections,struct
                                actual=collections.Counter(struct.unpack_from('<i',data,64+64*i+8)[0] for i in range(count))
                                if any(actual[l]!=stats[v,str(role),str(ns),str(l)] for l in range(levels)):raise ValueError('T2 packet/stats octave mismatch')
                                rows.append(dict(path=p.relative_to(corpus).as_posix(),bytes=len(data),sha256=sha(p)));codec.append('%s\t%d\t%d\t%d\t%d\t%d\t%d\n'%(p,ns,role,d['width'],d['height'],levels,budget))
                    with (corpus/'manifest.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['path','bytes','sha256'],lineterminator='\n');w.writeheader();w.writerows(rows)
                    (corpus/'codec.tsv').write_text(''.join(codec))
                    with (corpus/'codec.log').open('w') as log:subprocess.run([str(probe),str(corpus/'codec.tsv'),str(corpus/'codec_roundtrip.orb')],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
                    if (corpus/'codec.log').read_text().strip()!='B1_ACTUAL_CODEC_BYTE_EXACT packets='+str(len(rows)):raise ValueError('Actual B1 codec gate did not finish')
                    for p in [corpus/'manifest.csv',corpus/'stats.csv',corpus/'codec.log']:state['frozen_runtime_sha256'][str(p)]=sha(p)
                    state['generated_dataset']=d['name'];state['generated_packets']=len(rows);save()
                prepared_h2=True
            d=next(d for d in datasets if d['name']==item['dataset']);v=item['variant'];run=out/'runs'/item['folder']
            state.update(phase='verify_reused_inputs',current=item['folder'],experiment_phase=item['phase']);save();frozen();images(d)
            if v!='native':
                corpus=pathlib.Path(d['feature_roots'][v]).parent
                for r in read_rows(corpus/'manifest.csv'):
                    if r['path'].startswith(v+'/') and sha(corpus/r['path'])!=r['sha256']:raise ValueError('Packet changed '+r['path'])
            state.update(phase='decision_runs');save()
            command=[sys.executable,str(source/'run_pc_slam.py'),'--binary',str(BINARY),'--vocabulary',str(VOCABULARY),'--yaml',d['configs'][v],'--dataset',d['path'],'--timestamps',d['timestamps'],'--output',str(run),'--sequence',d['name'],'--candidate',v,'--cores',','.join(map(str,state['cores'])),'--feature-mode','native' if v=='native' else 'inject','--wait-lock']
            if v!='native':command+=['--feature-directory',d['feature_roots'][v]]
            env=dict(os.environ,ORB_SELECTED_STATS=str(run/'SelectedPoints.csv'));env.pop('ORB_RELOC_DIAGNOSTICS',None)
            with (out/(item['folder']+'_runner.log')).open('w') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=env)
            meta=json.loads((run/'run_metadata.json').read_text());item.update(status=meta['status'],classification=classify(meta,run),exit_code=result.returncode)
            meta.update(intrinsics_label=d['intrinsics_label'],golden_sha256=state['golden_sha256'],control_flow_fix='0014; no RANSAC/matching parameters changed');atomic_json(run/'run_metadata.json',meta)
            state['completed']+=1;state['failed_slots']=sum(r['status']=='FAILED' for r in state['schedule']);save()
        state.update(phase='report',current=None);save()
        subprocess.run([sys.executable,str(source/'golden_report_audited.py'),'--batch-root',str(out)],check=True)
        subprocess.run([sys.executable,str(source/'h_round_report.py'),'--batch-root',str(out)],check=True)
        state.update(status='FINISHED_AWAIT_LAYER_DECISION',phase='await_user_layer_choice',finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat());save()
    except Exception as error:state.update(status='FAILED',error=str(error));save();raise
def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch name')
    if a.prepare_only:prepare(a.batch)
    else:execute(a.batch)
if __name__=='__main__':main()
