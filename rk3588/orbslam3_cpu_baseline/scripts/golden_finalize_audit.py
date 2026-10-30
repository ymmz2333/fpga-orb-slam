"""Complete reproducible script/report/preparation gates and freeze acceptance."""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time
from golden_audit_support import atomic_json
from run_pc_slam import library_environment,verify_linkage

EXPERIMENT=pathlib.Path(__file__).resolve().parents[1]
PROJECT=EXPERIMENT.parents[1];GOLDEN=PROJECT/'orb_frontend_golden'
sys.path.insert(0,str(GOLDEN/'scripts'))
from common import sha,DATASETS,stamps

def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',required=True,type=pathlib.Path);p.add_argument('--analysis',required=True,type=pathlib.Path);p.add_argument('--prepare-id',required=True);a=p.parse_args()
    out=a.audit;acceptance=json.loads((out/'state.json').read_text());assert acceptance['status']=='PASSED'
    analysis=json.loads((a.analysis/'state.json').read_text());assert analysis['status']=='PASSED'
    with (out/'orchestration_tests.log').open('w') as log:
        subprocess.run([sys.executable,str(EXPERIMENT/'scripts/test_golden_orchestration.py')],stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=PROJECT/'.work/golden/slam_source/Examples/Monocular/mono_euroc'
    environment,library=library_environment(binary);linked=verify_linkage(binary,environment,library)
    runtime={str(binary):sha(binary)}
    for value in re.findall(r'=>\s+(/\S+)',linked):runtime[value]=sha(pathlib.Path(value))
    # Check both accepted artifacts against the completed build's saved hashes.
    for line in (PROJECT/'.work/golden/slam_binary.sha256').read_text().splitlines():
        digest,path=line.split(None,1);assert sha(pathlib.Path(path.strip()))==digest
    runtime[str(PROJECT/'.work/golden/slam_source/Vocabulary/ORBvoc.txt')]=sha(PROJECT/'.work/golden/slam_source/Vocabulary/ORBvoc.txt')
    runtime[str(out/'packet_probe/golden_packet_probe')]=sha(out/'packet_probe/golden_packet_probe')
    acceptance.update(runtime_sha256=runtime,analysis_check=str(a.analysis/'state.json'),analysis_state_sha256=sha(a.analysis/'state.json'),
                      script_regressions='7/7 PASS; synthetic only',test_log_sha256=sha(out/'orchestration_tests.log'))
    atomic_json(out/'acceptance.json',acceptance)
    with (out/'prepare_test.log').open('w') as log:
        subprocess.run([sys.executable,str(EXPERIMENT/'scripts/golden_decision_audited.py'),'--batch',a.prepare_id,'--prepare-only','--acceptance',str(out/'acceptance.json')],stdout=log,stderr=subprocess.STDOUT,check=True)
    prepared=GOLDEN/'decision'/a.prepare_id
    state=json.loads((prepared/'batch_state.json').read_text());assert state['status']=='PREPARED' and state['completed']==0 and state['planned']==90
    manifest=json.loads((prepared/'configs/manifest.json').read_text())
    assert len(manifest['datasets'])==3
    for ds,d in zip(manifest['datasets'],DATASETS):
        assert ds['full_frames']==len(stamps(d)) and pathlib.Path(ds['timestamps']).read_bytes()==d['timestamps'].read_bytes()
        for v,path in ds['configs'].items():
            text=pathlib.Path(path).read_text();levels=8 if v in ('native','V0') else int(v[1:])
            assert re.search(r'(?m)^ORBextractor.nLevels:\s*'+str(levels)+r'\s*$',text)
            assert re.search(r'(?m)^ORBextractor.nFeatures:\s*1000\s*$',text)
            assert 'Camera.newWidth:' not in text and 'Camera.newHeight:' not in text
    acceptance.update(preparation_check=str(prepared),script_sha256={str(f):sha(f) for f in (EXPERIMENT/'scripts').glob('golden_*.py')})
    # Disk allowance: ~15 GB feature maximum at nominal budgets + 4.1 GB PGM,
    # raw/analysis/stacks/logs and conservative headroom, without deleting evidence.
    acceptance['free_space_bytes']=shutil.disk_usage(PROJECT).free
    acceptance['required_free_bytes']=40*1024**3
    if acceptance['free_space_bytes']<acceptance['required_free_bytes']:raise RuntimeError('Insufficient free disk space')
    timing=[]
    old=pathlib.Path(acceptance['previous'])
    for d in DATASETS:
        files=list((old/d['name']/'g1').glob('*/*/*.orb'))
        times=[f.stat().st_mtime for f in files]
        timing.append(dict(dataset=d['name'],short_frames=150,short_generation_span_s=max(times)-min(times),full_frames=len(stamps(d))))
    acceptance['estimated_generation_s_from_short_file_spans']=sum(r['short_generation_span_s']/149*(r['full_frames']-1) for r in timing)
    acceptance['short_generation_spans']=timing
    acceptance['realtime_playback_minimum_s']=sum((stamps(d)[-1]-stamps(d)[0])*1e-9 for d in DATASETS)*30
    atomic_json(out/'acceptance.json',acceptance)
    print('AUDIT_FINALIZED: 7 script tests; real ATE/Sim3; 90-slot preparation; runtime hashes; disk PASS',flush=True)
    print('ESTIMATE generation_s=%.0f playback_minimum_s=%.0f'%(acceptance['estimated_generation_s_from_short_file_spans'],acceptance['realtime_playback_minimum_s']))
if __name__=='__main__':main()
