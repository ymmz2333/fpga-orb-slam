"""Counter-only reproduction and data-gated diagnosis. Never changes solver logic."""
import argparse,csv,json,os,pathlib,subprocess,sys
from golden_audit_support import atomic_json,classify
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--fixed',action='store_true');a=p.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=False)
    prior=PROJECT/'orb_frontend_golden/decision/G1_layers_resume_20261006_013559'
    d=json.loads((prior/'configs/manifest.json').read_text())['datasets'][2]
    ns=list(map(int,pathlib.Path(d['timestamps']).read_text().split()))[:600]
    stamps=out/'timestamps600.txt';stamps.write_text(''.join(str(n)+'\n' for n in ns))
    run=out/'run';env=dict(os.environ,ORB_RELOC_DIAGNOSTICS=str(run/'RelocalizationCounters.csv'))
    if a.fixed:env['ORB_SELECTED_STATS']=str(run/'SelectedPoints.csv')
    build='fixed_v1' if a.fixed else 'diagnostic'
    cmd=[sys.executable,str(ROOT/'scripts/run_pc_slam.py'),'--binary',str(PROJECT/'.work/golden_h1'/build/'slam_source/Examples/Monocular/mono_euroc'),
        '--vocabulary',str(PROJECT/'.work/golden/slam_source/Vocabulary/ORBvoc.txt'),'--yaml',d['configs']['L8'],'--dataset',d['path'],
        '--timestamps',str(stamps),'--output',str(run),'--sequence',d['name'],'--candidate','H1_L8_fixed_smoke' if a.fixed else 'H1_L8_counter_only',
        '--cores','0,2,4,6','--feature-mode','inject','--feature-directory',str(pathlib.Path(d['corpus'])/'L8'),'--wait-lock']
    atomic_json(out/'state.json',dict(status='RUNNING',phase='counter_only_reproduction',frames=600,parameters_changed=False))
    with (out/'runner.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=env)
    meta=json.loads((run/'run_metadata.json').read_text());classification=classify(meta,run)
    if a.fixed:
        states=list(csv.DictReader((run/'TrackingStates.csv').open()));maps=list(csv.DictReader((run/'MapStateStats.csv').open()))
        evidence=dict(status='PASSED' if classification=='COMPLETED' and len(states)==600 else 'FAILED_STOP',completed_frames=len(states),classification=classification,
            near_original_hang=[dict(s,**{k:v for k,v in m.items() if k not in s}) for s,m in zip(states[137:160],maps[137:160])],
            relocated=sum(int(m['relocalized']) for m in maps),map_ids_observed=sorted({m['map_id'] for m in maps}),parameters_changed=False)
        atomic_json(out/'fixed_acceptance.json',evidence);atomic_json(out/'state.json',dict(status=evidence['status'],phase='fixed_smoke_complete'))
        print(json.dumps({k:v for k,v in evidence.items() if k!='near_original_hang'}),flush=True)
        return 0 if evidence['status']=='PASSED' else 1
    with (run/'RelocalizationCounters.csv').open() as f:rows=list(csv.DictReader(f))
    returns=[r for r in rows if r['event']=='refine_return'];exhausted=[r for r in returns if int(r['total_iteration'])>=int(r['max_iterations']) and r['bNoMore']=='0']
    pose=[r for r in rows if r['event']=='pose_optimization'];outer=[r for r in rows if r['event']=='outer_solver']
    maximum=max([int(r['total_iteration']) for r in returns],default=0)
    evidence=dict(status='CONFIRMED' if classification=='CANDIDATE_HANG_RETAINED' and len(exhausted)>2 and maximum>max(int(r['max_iterations']) for r in exhausted) else 'UNCONFIRMED_STOP',
        completed_frames=meta['completed_frames'],classification=classification,trace_rows=len(rows),exhausted_returns_with_bNoMore_false=len(exhausted),
        max_total_iterations=maximum,configured_max_iterations=sorted({int(r['max_iterations']) for r in returns}),outer_rounds=max([int(r['outer_round']) for r in outer],default=0),
        exhausted_frame_ids=sorted(set(int(r['frame_id']) for r in exhausted)),
        pose_inliers_min=min([int(r['pose_inliers']) for r in pose],default=None),pose_inliers_max=max([int(r['pose_inliers']) for r in pose],default=None),
        proposed_fix='Set bNoMore = (mnIterations >= mRansacMaxIts) immediately before Refine-success return; retain OR loop, thresholds and algorithm parameters',
        parameters_changed=False,logic_changed=False)
    atomic_json(out/'diagnosis.json',evidence);atomic_json(out/'state.json',dict(status=evidence['status'],phase='diagnosis_complete'))
    print(json.dumps(evidence),flush=True)
    return 0 if evidence['status']=='CONFIRMED' else 1
if __name__=='__main__':raise SystemExit(main())
