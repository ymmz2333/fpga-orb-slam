#!/usr/bin/env python3
"""Independent retained-raw transport, sampling, coverage, timing and configuration gates."""
import argparse
import csv
import hashlib
import json
import pathlib

ROOT=pathlib.Path(__file__).resolve().parent.parent

def verify(report):
    checks=[]
    def gate(name,condition,detail):
        checks.append(dict(check=name,status='PASS' if condition else 'FAIL',detail=detail))
    state=json.loads((report/'batch_state.json').read_text(encoding='utf-8'))
    gate('batch_finished',state['status']=='FINISHED' and state['completed']==state['planned']==10,'native/inject each five attempts')
    with (report/'raw_manifest.csv').open() as f: manifest=list(csv.DictReader(f))
    matched=0
    folders={i['folder'] for i in state['schedule']} | {state['dump']['folder']}
    # Audit the retained report itself, so a clean checkout needs neither runtime nor the board.
    for row in manifest:
        relative=pathlib.Path(row['path'])
        path=(report/'raw'/relative) if relative.parts[0] in folders else (report/relative)
        if path.exists() and path.stat().st_size==int(row['bytes']) and hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']:
            matched+=1
    gate('board_to_pc_hashes',matched==len(manifest),'matched=%d/%d'%(matched,len(manifest)))
    full=state['verification']
    gate('full_feature_memory_equality',full['status']=='PASS' and full['files']==7364 and full['byte_mismatches']==0 and not full['synthetic_only'],
         '7364 packets; points=%d; compared_bytes=%d'%(full['points'],full['bytes_compared']))
    hashes=set(); binaries=set()
    timestamps=[int(x) for x in (ROOT/'reports/a2/MH01.txt').read_text().splitlines() if x.strip()]
    with (report/'verification/feature_verification.csv').open() as f:
        corpus={(int(r['timestamp_ns']),int(r['role'])):int(r['point_count']) for r in csv.DictReader(f)}
    for item in state['schedule']:
        folder=report/'raw'/item['folder']; m=json.loads((folder/'run_metadata.json').read_text(encoding='utf-8'))
        with (folder/'FeatureTimeStats.csv').open() as f: features=list(csv.DictReader(f))
        with (folder/'TrackingStates.csv').open() as f: states=list(csv.DictReader(f))
        with (folder/'telemetry.csv').open() as f: samples=list(csv.DictReader(f))
        ate=json.loads((folder/'ate.json').read_text()); facts=json.loads((folder/'b1_facts.json').read_text())
        hashes.add(m['settings_sha256']); binaries.add(m['binary_sha256'])
        prefix=item['folder']+'/'
        gate(prefix+'completed',m['status']=='FINISHED' and m['exit_code']==0 and len(features)==len(states)==3682,'3682 aligned input frames')
        gate(prefix+'no_extractor_inject',all(int(r['extractor_calls'])==(0 if item['mode']=='inject' else 1) for r in features),'mode='+item['mode'])
        gate(prefix+'exact_timestamp_and_count',len(features)==len(timestamps) and
             all(int(r['timestamp_ns'])==ns and int(r['count'])==corpus.get((ns,int(r['role']))) for r,ns in zip(features,timestamps)),
             'exact integer input timestamps; selected-role counts equal verified corpus')
        gate(prefix+'restoration',m['governors_restored'] and m['dmc_restored'],'original CPU interactive, DMC dmc_ondemand restored')
        target=m['dmc_target_hz']
        observed=all(int(s['dmc_cur_hz'])==int(s['dmc_max_hz'])==target for s in samples)
        cpu=all(int(s[p+'_cur_khz'])==int(s[p+'_max_khz'])==m['expected_max_khz'][p]
                for s in samples if s['phase']=='tracking_or_shutdown' for p in ('policy4','policy6'))
        gate(prefix+'fixed_cpu_ddr',observed and cpu and not(m['frequency_drop_detected'] or m['dmc_frequency_drop'] or m['thermal_cap_detected']),
             'DMC=1560000000Hz, A76=2256000kHz; samples='+str(len(samples)))
        gate(prefix+'evo_numpy',ate['evaluation_method'].startswith('evo ') and abs(ate['ate_rmse_m']-ate['numpy_rmse_m'])<1e-9,'3638 associated camera poses; Sim3')
        gate(prefix+'gt_tracking',facts['gt_lost_frames']==0 and facts['gt_ok_frames']==facts['gt_input_frames'],'all ground-truth-covered input frames are OK')
        gate(prefix+'map_and_end',facts['maps']==1 and facts['last_state']==2 and facts['active_map_resets']==facts['full_resets']==0,'one map; no resets; final OK')
    gate('same_settings_binary',len(hashes)==len(binaries)==1,'same YAML and binary SHA256 across ten attempts')
    with (report/'acceptance.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(checks[0])); w.writeheader(); w.writerows(checks)
    result=dict(status='PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL',checks=len(checks),failed=[c for c in checks if c['status']=='FAIL'])
    (report/'acceptance.json').write_text(json.dumps(result,indent=2))
    print('B1_RAW_CHECKS '+json.dumps(result))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('report',type=pathlib.Path); a=p.parse_args()
    result=verify(a.report)
    if result['status']!='PASS': raise SystemExit(1)
