"""Authorized 90-slot G1 layer decision round, PC/WSL only; stop at v0.9 report."""
import argparse
import csv
import datetime
import fcntl
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import cv2
EXPERIMENT=pathlib.Path(__file__).resolve().parents[1]
PROJECT=EXPERIMENT.parents[1]
ROOT=PROJECT/'orb_frontend_golden'
sys.path.insert(0,str(ROOT/'scripts'))
from common import DATASETS,stamps,pgm,sha
from golden_audit_support import atomic_json as write_json, packet, CompletedProgress, classify, write_timestamps
from run_pc_slam import library_environment,verify_linkage,allow_diagnostic_ptrace,capture
from compare import validate_packet

VARIANTS=['native','V0','L8','L4','L2','L1']

def schedule():
    result=[];alternatives=VARIANTS[1:]
    for repeat in range(1,6):
        shift=(repeat-1)%5;rotated=alternatives[shift:]+alternatives[:shift]
        ds=DATASETS[(repeat-1)%3:]+DATASETS[:(repeat-1)%3]
        for variant in ['native']+rotated:
            for d in ds:
                result.append(dict(dataset=d['name'],variant=variant,run_index=repeat,
                    folder=d['name']+'__'+variant+'__run%02d'%repeat,status='PENDING'))
    assert len(result)==90
    return result

def cores():
    topology=subprocess.check_output(['lscpu','-p=CPU,CORE,SOCKET'],text=True);seen=set();selected=[]
    for line in topology.splitlines():
        if line.startswith('#'):continue
        cpu,core,socket=map(int,line.split(','))
        if cpu in os.sched_getaffinity(0) and (socket,core) not in seen:
            selected.append(cpu);seen.add((socket,core))
    if len(selected)<4:raise RuntimeError('Cannot choose 4 physical-core representatives')
    return selected[:4],topology

def verify_corpus(folder,d,probe,environment):
    count=0;manifest=[]
    codec=[]
    for variant in VARIANTS[1:]:
        levels=8 if variant=='V0' else int(variant[1:])
        for role,n in [('normal',1000),('initialization',5000)]:
            for ns in map(int,pathlib.Path(d['timestamps']).read_text().split()):
                file=folder/variant/role/(str(ns)+'.orb');b=file.read_bytes()
                points=packet(b,ns,int(role=='initialization'),d['width'],d['height'],levels,n)
                if variant!='V0':assert points<=n
                manifest.append(dict(path=file.relative_to(folder).as_posix(),bytes=len(b),sha256=sha(file)));count+=1
                codec.append('%s\t%d\t%d\t%d\t%d\t%d\t%d\n'%(file,ns,int(role=='initialization'),d['width'],d['height'],levels,n))
    with (folder/'manifest.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);writer.writeheader();writer.writerows(manifest)
    (folder/'codec.tsv').write_text(''.join(codec))
    with (folder/'codec.log').open('w') as log:
        subprocess.run([str(probe),str(folder/'codec.tsv'),str(folder/'codec_roundtrip.orb')],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    return count

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',required=True);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--start-after-delivery',action='store_true')
    parser.add_argument('--acceptance',required=True,type=pathlib.Path)
    a=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch ID')
    output=ROOT/'decision'/a.batch;output.mkdir(parents=True,exist_ok=False)
    chosen,topology=cores();items=schedule();scratch=PROJECT/'.work/golden'
    acceptance=json.loads(a.acceptance.read_text())
    if acceptance.get('status')!='PASSED':raise ValueError('Audited infrastructure gates not passed')
    state=dict(status='PREPARED',phase='prepared',planned=90,completed=0,schedule=items,platform='x86 PC / WSL2',
        cores=chosen,affinity_basis='One logical CPU per distinct WSL CPU/CORE/SOCKET; host Ryzen 8 physical/16 logical',
        no_failure_replacement=True,forced_loss=False,performance_conclusions=False,v0_semantics='G1 simplifications-off integer control; not original float byte-equivalent V0',
        golden_sha256=sha(ROOT/'build/orb_golden_cli'),started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    (output/'topology.txt').write_text(topology)
    def save():
        temp=output/'batch_state.tmp';write_json(temp,state);temp.replace(output/'batch_state.json')
    save()
    # Freeze source/settings/producers so unrelated future workspace edits cannot change this round.
    sources=output/'source';sources.mkdir()
    for name in ['common.py','compare.py']:
        shutil.copy2(ROOT/'scripts'/name,sources/name)
    for name in ['run_pc_slam.py','analyze_a2.py','analyze_c.py','evaluate_a2.py','finish_c.py','golden_audit_support.py','golden_report_audited.py','golden_decision_audited.py']:
        shutil.copy2(EXPERIMENT/'scripts'/name,sources/name)
    shutil.copy2(ROOT/'build/orb_golden_cli',sources/'orb_golden_cli')
    datasets=[]
    for index,d in enumerate(DATASETS):
        ds=dict(d);ds.update(path=str(d['path']),timestamps=str(d['timestamps']),full_frames=len(stamps(d)),
            kind='euroc' if index==0 else 'prepared',width=752 if index==0 else 960,height=480 if index==0 else 720,
            intrinsics_label=d['label'],configs={})
        folder=output/'configs'/d['name'];folder.mkdir(parents=True)
        timestamp=folder/'timestamps.txt';write_timestamps(d['timestamps'],timestamp);ds['timestamps']=str(timestamp)
        original=(EXPERIMENT/('configs/a3/baseline_752x480.yaml' if index==0 else 'configs/c/tello_oafd_960x720_provisional.yaml')).read_text()
        for variant in VARIANTS:
            text=original;levels=8 if variant in ['native','V0'] else int(variant[1:])
            for field,value in [('nFeatures',1000),('nLevels',levels),('scaleFactor',1.2),('iniThFAST',20),('minThFAST',7)]:
                text,n=re.subn(r'(?m)^(ORBextractor\.'+field+r':)\s*[^\n]+',lambda m:m[1]+' '+str(value),text)
                if n!=1:raise ValueError('Invalid YAML field '+field)
            yaml=folder/(variant+'.yaml');yaml.write_text(text);ds['configs'][variant]=str(yaml)
        datasets.append(ds)
    write_json(output/'configs/manifest.json',dict(datasets=datasets,plan=dict(variants=VARIANTS,scaleFactor=1.2,normal=1000,initialization=5000,rounds=5)))
    if a.prepare_only:print('B3_DECISION_PREPARED',output);return 0
    if not a.start_after_delivery:raise ValueError('Report G1/G2/G3/G4 first; then use --start-after-delivery')
    if not (ROOT/'delivery/DELIVERY_REPORT.md').exists():raise ValueError('Delivery report missing')
    try:
        lock=(output.parent/'decision.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state.update(status='RUNNING',phase='verify_frozen_native');save()
        binary=scratch/'slam_source/Examples/Monocular/mono_euroc';vocabulary=scratch/'slam_source/Vocabulary/ORBvoc.txt'
        if sha(binary)!=acceptance['binary_sha256']:raise RuntimeError('Accepted SLAM binary changed')
        environment,library=library_environment(binary)
        linkage=verify_linkage(binary,environment,library);(output/'linkage.ldd.txt').write_text(linkage)
        for path,digest in acceptance['runtime_sha256'].items():
            if sha(pathlib.Path(path))!=digest:raise RuntimeError('Accepted runtime changed: '+path)
        # Freeze the identities of every resolved runtime library, settings, scripts and vocabulary.
        dependencies={str(path):sha(path) for path in [binary,vocabulary,*sources.glob('*'),* (output/'configs').rglob('*')] if path.is_file()}
        for lib in re.findall(r'=>\s+(/\S+)',linkage):dependencies[lib]=sha(pathlib.Path(lib))
        state['frozen_runtime_sha256']=dependencies
        probe=a.acceptance.resolve().parent/'packet_probe/golden_packet_probe'
        if not probe.exists():raise ValueError('Accepted actual B1 codec probe missing')
        dependencies[str(probe)]=sha(probe)
        state.update(slam_sha256=sha(binary),library_sha256=sha(scratch/'slam_source/lib/libORB_SLAM3.so'));save()
        state['phase']='generate_g1_corpus';save();cv2.setNumThreads(1)
        for d in datasets:
            prepared=output/'prepared_pgm'/d['name'];prepared.mkdir(parents=True)
            input_manifest=[]
            for index,ns in enumerate(map(int,pathlib.Path(d['timestamps']).read_text().split())):
                image=pathlib.Path(d['path'])/'mav0/cam0/data'/(str(ns)+'.png')
                image_hash=sha(image);im=cv2.imread(str(image),0)
                if im is None:raise ValueError('Missing dataset frame')
                if im.shape!=(d['height'],d['width']):raise ValueError('Dataset image dimensions differ')
                if sha(image)!=image_hash:raise ValueError('Source changed during decode')
                pgm(prepared/(str(ns)+'.pgm'),im)
                input_manifest.append(dict(timestamp_ns=ns,source_sha256=image_hash,pgm_sha256=sha(prepared/(str(ns)+'.pgm'))))
                if index%100==0:state.update(current=d['name'],decoded_frames=index+1);save()
            write_json(prepared/'input_hashes.json',input_manifest)
            corpus=output/'corpus'/d['name'];corpus.mkdir(parents=True)
            state.update(current=d['name'],generation_phase='C++ integer frontend',generated_frames=0);save()
            generation_log=output/(d['name']+'_generate.log')
            with generation_log.open('w') as log:
                child=subprocess.Popen([str(sources/'orb_golden_cli'),'--input',str(prepared),'--sequence',str(d['timestamps']),
                    '--output',str(corpus)],stdout=log,stderr=subprocess.STDOUT,preexec_fn=allow_diagnostic_ptrace)
                progress=CompletedProgress(time.monotonic())
                while child.poll() is None:
                    time.sleep(5);size=generation_log.stat().st_size
                    with generation_log.open('rb') as reader:
                        reader.seek(max(0,size-4096));tail=reader.read().decode(errors='replace')
                    expired=progress.observe(tail,time.monotonic())
                    if progress.frames>=0:state['generated_frames']=progress.frames;save()
                    if expired:
                        snapshot=output/(d['name']+'_generation_hang');snapshot.mkdir()
                        write_json(snapshot/'capture.json',capture(child.pid,snapshot))
                        child.terminate()
                        try:child.wait(timeout=15)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                        raise RuntimeError('G1 generation completed-frame watchdog expired: '+d['name'])
                if child.returncode:raise subprocess.CalledProcessError(child.returncode,child.args)
            count=verify_corpus(corpus,d,probe,environment);state.update(generated_dataset=d['name'],generated_packets=count);save()
        state['phase']='decision_runs';save()
        for item in items:
            d=next(d for d in datasets if d['name']==item['dataset']);variant=item['variant'];run=output/'runs'/item['folder']
            state['current']=item['folder'];save()
            state['phase']='decision_runs';save()
            for path,digest in dependencies.items():
                if sha(pathlib.Path(path))!=digest:raise RuntimeError('Frozen runtime input changed: '+path)
            for record in json.loads((output/'prepared_pgm'/d['name']/'input_hashes.json').read_text()):
                image=pathlib.Path(d['path'])/'mav0/cam0/data'/(str(record['timestamp_ns'])+'.png')
                if sha(image)!=record['source_sha256']:raise RuntimeError('Frozen source image changed: '+str(image))
            if variant!='native':
                for record in csv.DictReader((output/'corpus'/d['name']/'manifest.csv').open()):
                    if record['path'].startswith(variant+'/') and sha(output/'corpus'/d['name']/record['path'])!=record['sha256']:
                        raise RuntimeError('Frozen feature packet changed: '+record['path'])
            cmd=[sys.executable,str(sources/'run_pc_slam.py'),'--binary',str(binary),'--vocabulary',str(vocabulary),
                '--yaml',d['configs'][variant],'--dataset',d['path'],'--timestamps',d['timestamps'],'--output',str(run),
                '--sequence',d['name'],'--candidate',variant,'--cores',','.join(map(str,chosen)),
                '--feature-mode','native' if variant=='native' else 'inject','--wait-lock']
            if variant!='native':cmd+=['--feature-directory',str(output/'corpus'/d['name']/variant)]
            with (output/(item['folder']+'_runner.log')).open('w') as log:
                result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
            meta=run/'run_metadata.json'
            item.update(status=json.loads(meta.read_text())['status'] if meta.exists() else 'RUNNER_FAILED',exit_code=result.returncode)
            if meta.exists():
                m=json.loads(meta.read_text());m.update(intrinsics_label=d['intrinsics_label'],golden_sha256=state['golden_sha256'],
                    v0_semantics=state['v0_semantics'] if variant=='V0' else None);write_json(meta,m)
                classification=classify(m,run)
                item['classification']=classification
            else:raise RuntimeError('Runner exited without trustworthy terminal metadata')
            state['completed']+=1;save()
            state['failed_slots']=sum(slot['status']=='FAILED' for slot in items);save()
        state['phase']='report';save()
        subprocess.run([sys.executable,str(sources/'golden_report_audited.py'),'--batch-root',str(output)],check=True)
        state.update(status='FINISHED_AWAIT_LAYER_DECISION',phase='await_user_layer_choice',current=None);save()
        print('B3_DECISION_FINISHED_STOPPED',output);return 0
    except Exception as error:
        state.update(status='FAILED',error=str(error));save();raise
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        # Preparation errors occur before the main try block as well.
        if '--batch' in sys.argv:
            path=ROOT/'decision'/sys.argv[sys.argv.index('--batch')+1]/'batch_state.json'
            if path.exists():
                state=json.loads(path.read_text());state.update(status='FAILED',error=str(error));write_json(path,state)
        raise
