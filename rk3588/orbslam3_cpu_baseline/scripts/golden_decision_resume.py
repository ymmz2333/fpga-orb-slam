"""Resume unattempted slots; reuse verified features and retain every terminal run."""
import argparse
import copy
import csv
import datetime
import fcntl
import json
import pathlib
import re
import shutil
import subprocess
import sys
from golden_audit_support import atomic_json,canonical_timestamps,write_timestamps,classify,read_rows
from golden_decision_audited import ROOT,PROJECT,EXPERIMENT,VARIANTS,schedule,cores,sha
from run_pc_slam import library_environment,verify_linkage


def inherited_run(folder,item,expected):
    metadata=json.loads((folder/'run_metadata.json').read_text())
    if metadata['status'] not in ('FINISHED','FAILED'):raise ValueError('Nonterminal prior run; require investigation')
    frames=read_rows(folder/'TrackingStates.csv')
    if len(frames)!=metadata['completed_frames']:raise ValueError('Prior frame count mismatch')
    if metadata['status']=='FINISHED':
        if metadata['exit_code']!=0 or len(frames)!=expected:raise ValueError('Invalid prior completed run')
        outcome='COMPLETED'
    elif metadata['completed_frames']==0 and 'Failed to load image at:' in (folder/'run.log').read_text(errors='replace'):
        outcome='INPUT_SETUP_FAILURE_RETAINED_NO_RETRY'
    elif metadata.get('failure_reason','').startswith('INPUT_TIMESTAMP_FORMAT:'):
        outcome='INPUT_SETUP_FAILURE_RETAINED_NO_RETRY'
    else:outcome=classify(metadata,folder)
    return metadata['status'],outcome


def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--acceptance',required=True,type=pathlib.Path);p.add_argument('--resume-from',required=True,type=pathlib.Path);p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Unsafe batch ID')
    old=a.resume_from.resolve();previous=json.loads((old/'batch_state.json').read_text())
    if previous['status'] not in ('FAILED','STOPPED_FOR_HANDOFF'):raise ValueError('Prior batch must be stopped')
    acceptance=json.loads(a.acceptance.read_text());assert acceptance['status']=='PASSED'
    output=ROOT/'decision'/a.batch;output.mkdir(exist_ok=False)
    state=dict(status='PREPARING',phase='resume_preparation',planned=90,completed=0,schedule=schedule(),platform='x86 PC / WSL2',
        resumed_from=str(old),previous_state_sha256=sha(old/'batch_state.json'),no_failure_replacement=True,forced_loss=False,performance_conclusions=False,
        v0_semantics=previous['v0_semantics'],golden_sha256=previous['golden_sha256'],started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    def save():atomic_json(output/'batch_state.json',state)
    save()
    try:
        lock=(output.parent/'decision.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        binary=PROJECT/'.work/golden/slam_source/Examples/Monocular/mono_euroc';vocabulary=binary.parents[2]/'Vocabulary/ORBvoc.txt'
        if sha(binary)!=previous['slam_sha256'] or sha(ROOT/'build/orb_golden_cli')!=state['golden_sha256']:raise ValueError('Accepted algorithm binary changed')
        # The original snapshots are immutable, including their faulty timestamp copy.
        for path,digest in previous['frozen_runtime_sha256'].items():
            if sha(pathlib.Path(path))!=digest:raise ValueError('Original frozen runtime changed: '+path)
        for path,digest in acceptance['runtime_sha256'].items():
            if sha(pathlib.Path(path))!=digest:raise ValueError('Accepted runtime changed: '+path)
        env,library=library_environment(binary);linked=verify_linkage(binary,env,library);(output/'linkage.ldd.txt').write_text(linked)
        assets=pathlib.Path(previous.get('source_assets_from',str(old)))
        state['source_assets_from']=str(assets)
        old_manifest=json.loads((old/'configs/manifest.json').read_text());datasets=[]
        source=output/'source';source.mkdir()
        for name in ('run_pc_slam.py','golden_audit_support.py','golden_report_audited.py','golden_decision_resume.py','analyze_c.py','analyze_a2.py','evaluate_a2.py','finish_c.py'):
            shutil.copy2(EXPERIMENT/'scripts'/name,source/name)
        chosen,topology=cores();state['cores']=chosen;(output/'topology.txt').write_text(topology)
        dependencies={str(binary):sha(binary),str(vocabulary):sha(vocabulary)}
        for lib in re.findall(r'=>\s+(/\S+)',linked):dependencies[lib]=sha(pathlib.Path(lib))
        for path in source.iterdir():dependencies[str(path)]=sha(path)
        for ds0 in old_manifest['datasets']:
            ds=copy.deepcopy(ds0);folder=output/'configs'/ds['name'];folder.mkdir(parents=True)
            timestamp=folder/'timestamps.txt';ns=write_timestamps(ds0['timestamps'],timestamp);ds['timestamps']=str(timestamp)
            if len(ns)!=ds['full_frames']:raise ValueError('Frame count changed')
            dependencies[str(timestamp)]=sha(timestamp)
            ds['configs']={}
            for v,path in ds0['configs'].items():
                new=folder/(v+'.yaml');shutil.copy2(path,new);ds['configs'][v]=str(new);dependencies[str(new)]=sha(new)
            corpus=assets/'corpus'/ds['name'];manifest=corpus/'manifest.csv';records=read_rows(manifest)
            expected={v+'/'+r+'/'+str(t)+'.orb' for v in VARIANTS[1:] for r in ('normal','initialization') for t in ns}
            if len(records)!=len(expected) or {r['path'] for r in records}!=expected:raise ValueError('Incomplete feature corpus index')
            expected_codec='B1_ACTUAL_CODEC_BYTE_EXACT packets='+str(len(expected))
            if (corpus/'codec.log').read_text().strip()!=expected_codec:raise ValueError('Missing completed actual codec evidence')
            dependencies[str(manifest)]=sha(manifest);dependencies[str(corpus/'codec.log')]=sha(corpus/'codec.log')
            images=assets/'prepared_pgm'/ds['name']/'input_hashes.json';dependencies[str(images)]=sha(images)
            ds.update(corpus=str(corpus),input_hashes=str(images),source_codec_checked_packets=len(records))
            datasets.append(ds)
        atomic_json(output/'configs/manifest.json',dict(datasets=datasets,plan=old_manifest['plan']))
        dependencies[str(output/'configs/manifest.json')]=sha(output/'configs/manifest.json')
        state['frozen_runtime_sha256']=dependencies;state['slam_sha256']=sha(binary);state['library_sha256']=sha(binary.parents[2]/'lib/libORB_SLAM3.so')
        # Retain terminal slots, including input-setup failures; never retry them.
        prior={r['folder']:r for r in previous['schedule']}
        for item in state['schedule']:
            folder=old/'runs'/item['folder'];m=folder/'run_metadata.json'
            if m.exists():
                ds=next(d for d in datasets if d['name']==item['dataset'])
                status,outcome=inherited_run(folder,item,ds['full_frames'])
                target=output/'runs'/item['folder'];shutil.copytree(folder,target)
                item.update(status=status,classification=outcome,inherited_from=str(folder),exit_code=prior[item['folder']].get('exit_code'))
                if outcome=='INPUT_SETUP_FAILURE_RETAINED_NO_RETRY':item['failure_explanation']='Input setup failure before any completed frame; original failure retained, not retried or treated as algorithm failure'
            elif folder.exists() or prior[item['folder']]['status']!='PENDING':raise ValueError('Untrustworthy prior run lacks terminal metadata')
        state['completed']=sum(i['status']!='PENDING' for i in state['schedule']);state['failed_slots']=sum(i['status']=='FAILED' for i in state['schedule']);state['inherited_terminal_slots']=state['completed']
        state.update(status='PREPARED',phase='resume_prepared');save()
        if a.prepare_only:print('RESUME_PREPARED no generation; terminal slots retained='+str(state['completed']));return 0
        state.update(status='RUNNING',phase='decision_runs');save()
        for item in state['schedule']:
            if item['status']!='PENDING':continue
            ds=next(d for d in datasets if d['name']==item['dataset']);variant=item['variant'];run=output/'runs'/item['folder']
            state.update(phase='verify_reused_inputs',current=item['folder']);save()
            for path,digest in dependencies.items():
                if sha(pathlib.Path(path))!=digest:raise ValueError('Frozen dependency changed: '+path)
            for r in json.loads(pathlib.Path(ds['input_hashes']).read_text()):
                image=pathlib.Path(ds['path'])/'mav0/cam0/data'/(str(r['timestamp_ns'])+'.png')
                if sha(image)!=r['source_sha256']:raise ValueError('Source image changed: '+str(image))
            if variant!='native':
                records=[r for r in read_rows(pathlib.Path(ds['corpus'])/'manifest.csv') if r['path'].startswith(variant+'/')]
                state.update(verified_packets=0,packets_to_verify=len(records));save()
                for index,r in enumerate(records):
                    if sha(pathlib.Path(ds['corpus'])/r['path'])!=r['sha256']:raise ValueError('Reused packet hash mismatch: '+r['path'])
                    if index%1000==0:state['verified_packets']=index+1;save()
            state.update(phase='decision_runs');save()
            command=[sys.executable,str(source/'run_pc_slam.py'),'--binary',str(binary),'--vocabulary',str(vocabulary),'--yaml',ds['configs'][variant],
                '--dataset',ds['path'],'--timestamps',ds['timestamps'],'--output',str(run),'--sequence',ds['name'],'--candidate',variant,
                '--cores',','.join(map(str,chosen)),'--feature-mode','native' if variant=='native' else 'inject','--wait-lock']
            if variant!='native':command+=['--feature-directory',str(pathlib.Path(ds['corpus'])/variant)]
            with (output/(item['folder']+'_runner.log')).open('w') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            m=json.loads((run/'run_metadata.json').read_text());m.update(intrinsics_label=ds['intrinsics_label'],golden_sha256=state['golden_sha256'],v0_semantics=state['v0_semantics'] if variant=='V0' else None);atomic_json(run/'run_metadata.json',m)
            item.update(status=m['status'],classification=classify(m,run),exit_code=result.returncode)
            state['completed']+=1;state['failed_slots']=sum(i['status']=='FAILED' for i in state['schedule']);save()
        state.update(phase='report');save()
        subprocess.run([sys.executable,str(source/'golden_report_audited.py'),'--batch-root',str(output)],check=True)
        state.update(status='FINISHED_AWAIT_LAYER_DECISION',phase='await_user_layer_choice',current=None);save();return 0
    except Exception as error:
        state.update(status='FAILED',error=str(error));save();raise

if __name__=='__main__':raise SystemExit(main())
