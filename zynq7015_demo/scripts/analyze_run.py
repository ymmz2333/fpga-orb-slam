"""Summarize recorded board timings and optional same-dataset pose diagnostics."""
from pathlib import Path
import argparse,csv,json,math,statistics,re
p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--reference',type=Path);a=p.parse_args()
def rows(path):
    with path.open(newline='') as f:return list(csv.DictReader(f))
def log_rows(path):
    if path.exists():return rows(path)
    parts=[p for p in path.parent.glob(path.stem+'.part*'+path.suffix) if re.fullmatch(re.escape(path.stem)+r'\.part[0-9]{6,}'+re.escape(path.suffix),p.name)]
    parts.sort(key=lambda p:int(p.name[len(path.stem)+5:-len(path.suffix)]))
    if not parts:raise FileNotFoundError(path)
    return [row for part in parts for row in rows(part)]
def quantile(values,fraction):return sorted(values)[int((len(values)-1)*fraction)]
timing=log_rows(a.run/'timing.csv');trajectory=log_rows(a.run/'trajectory.csv');run=json.loads((a.run/'run.json').read_text())
assert 0<len(timing)==len(trajectory)<=run['processed']
full_history=len(timing)==run['processed']
if not run.get('log_segment_rows',0):assert full_history
assert [r['frame_index'] for r in timing]==[r['frame_index'] for r in trajectory]
result=dict(run=run,stages={},pose_states={},scope='Measured board run; average throughput and pose validity are separate acceptance dimensions')
result['log_scope']=dict(retained_rows=len(timing),total_processed=run['processed'],full_history=full_history,
    claim='Stage, pose-state and rolling-window statistics cover retained rows only; run counters cover the entire session')
for key in timing[0]:
    if key.endswith('_ms'):
        v=[float(r[key]) for r in timing];result['stages'][key]=dict(mean=statistics.mean(v),p50=statistics.median(v),p95=quantile(v,.95),maximum=max(v))
for row in trajectory:result['pose_states'][row['state']]=result['pose_states'].get(row['state'],0)+1
result['windows_300_fps']=[300000/sum(float(r['total_ms']) for r in timing[start:start+300]) for start in range(0,len(timing)-299,300)]
target=run.get('target_fps',60);window=int(target*10)
result['rolling_window_frames']=window
result['rolling_target10s_fps']=[window*1000/sum(float(r['total_ms']) for r in timing[start:start+window]) for start in range(0,len(timing)-window+1,max(1,int(target)))]
result['recovery_attempts']=sum(r.get('recovery_attempted','0')=='1' for r in timing)
result['acceptance_checks']=dict(physical_recording=run['mode']=='physical_orb' and run['input']=='recorded_gray8',
    complete_2273=run['processed']==2273 and full_history,golden_all_frames=run['golden_verified_frames']==run['processed'],
    frame_identity=[int(r['frame_index']) for r in timing]==list(range(int(timing[0]['frame_index']),int(timing[0]['frame_index'])+len(timing))),
    no_capture_drops=run['dropped_capture_frames']==0,aggregate_target_fps=run['processing_fps']>=target,
    log_complete_history=full_history,
    rolling_10s_target_fps=full_history and bool(result['rolling_target10s_fps']) and min(result['rolling_target10s_fps'])>=target)
if (a.run/'display.json').exists():result['display']=json.loads((a.run/'display.json').read_text())
if 'display' in result:
    result['acceptance_checks'].update(all_displayed=result['display']['submitted']==run['processed'],
        physical_hdmi=result['display']['interface'].startswith('HDMI_2'),
        no_scan_errors=result['display']['underruns']==result['display']['axi_errors']==0)
if a.reference:
    reference={int(r['frame_index']):r for r in rows(a.reference)};position=[];angle=[]
    for r in trajectory:
        other=reference[int(r['frame_index'])]
        if r['pose_valid']=='1' and other['pose_valid']=='1':
            position.append(math.sqrt(sum((float(r[f'twc_{i}3'])-float(other[f'twc_{i}3']))**2 for i in range(3))))
            trace=sum(float(r[f'twc_{i}{j}'])*float(other[f'twc_{i}{j}']) for i in range(3) for j in range(3))
            angle.append(math.degrees(math.acos(max(-1,min(1,(trace-1)/2)))))
    result['pose_diagnostic']=dict(common=len(position),reference_valid=sum(r['pose_valid']=='1' for r in reference.values()),
        position_median=quantile(position,.5),position_p95=quantile(position,.95),position_max=max(position),
        rotation_median_deg=quantile(angle,.5),rotation_p95_deg=quantile(angle,.95),rotation_max_deg=max(angle),
        scope='Original SLAM from same recording, same map coordinates, no alignment; not independent metric ground truth')
    result['pose_diagnostic']['reference_coverage']=len(position)/result['pose_diagnostic']['reference_valid']
(a.run/'analysis.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
