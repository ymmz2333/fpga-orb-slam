"""Read-only tracking diagnostics; never substitutes for performance evidence."""
import json
import math
import csv
from pathlib import Path

BUILD_STATUS='NATIVE_TRACKING_TRACE_BUILD_PASS'


def validate_config(config,build_status):
    enabled=config.get('tracking_trace',False)
    if type(enabled) is not bool:raise ValueError('tracking_trace must be a boolean')
    if enabled!=(build_status==BUILD_STATUS):raise ValueError('Tracking trace executable/config mismatch')
    if enabled and not config.get('profile',False):raise ValueError('Tracking diagnostics require profile=true; no performance acceptance')
    return enabled


def check(folder,actual):
    paths=sorted(Path(folder).glob('tracking_diagnostics.part*.jsonl'))
    if not paths:raise ValueError('Native tracking diagnostics missing')
    checked=0;lost=[];stages={}
    for path in paths:
        with path.open() as f:
            for line in f:
                row=json.loads(line)
                if checked>=len(actual):raise ValueError('Extra diagnostic frame')
                a=actual[checked]
                if (row['source_frame_id'],row['timestamp_ns'],row['features'],row['tracking_state'])!=tuple(int(a[k]) for k in ('source_frame_id','timestamp_ns','count','tracking_state')):
                    raise ValueError('Tracking diagnostic/source identity mismatch')
                if row.get('events_dropped') or len(row['levels'])!=8 or len(row['angle_bins'])!=32 or sum(row['levels'])!=int(a['count']) or sum(row['angle_bins'])!=int(a['count']):raise ValueError('Incomplete diagnostic features/events')
                pose=row['tcw']
                if bool(int(a['pose_valid']))!=(pose is not None) or (pose is not None and (len(pose)!=12 or not all(math.isfinite(x) for x in pose))):raise ValueError('Diagnostic pose validity mismatch')
                names=[e['stage'] for e in row['events']]
                if 'tracking_enter' not in names or 'tracking_exit' not in names:raise ValueError('Tracking branch trace is incomplete')
                for name in names:stages[name]=stages.get(name,0)+1
                if pose is None:lost.append(checked)
                checked+=1
    if checked!=len(actual):raise ValueError('Missing tracking diagnostic frames')
    return dict(status='NATIVE_TRACKING_TRACE_IDENTITIES_PASS',frames=checked,invalid_frames=lost,stage_counts=stages,
                scope='Observation only; profile=true timings are not performance acceptance')


def summarize(folder,journal,output):
    with Path(journal).open(newline='') as f:actual=list(csv.DictReader(f))
    proof=check(folder,actual);first=next((i for i,r in enumerate(actual) if int(r['pose_valid'])),None)
    lost=[i for i in proof['invalid_frames'] if first is not None and i>=first]
    segments=[]
    for i in lost:
        if not segments or i!=segments[-1][-1]+1:segments.append([i])
        else:segments[-1].append(i)
    starts=[s[0] for s in segments];wanted={i for s in starts for i in range(max(0,s-3),min(len(actual),s+4))};lost_set=set(lost)
    windows=[];failed_counts={};candidates=[]
    for path in sorted(Path(folder).glob('tracking_diagnostics.part*.jsonl')):
        with path.open() as f:
            for line in f:
                row=json.loads(line);i=row['source_frame_id']
                if i in wanted:windows.append(row)
                if i in lost_set:
                    for e in row['events']:
                        if e.get('accepted')==0:failed_counts[e['stage']]=failed_counts.get(e['stage'],0)+1
                        if e['stage']=='relocalization_candidates':candidates.append(e['count'])
    result=dict(status='NATIVE_TRACKING_BRANCH_DIAGNOSTIC_RECORDED',identity_proof=proof,first_valid_frame=first,
                post_initialization_invalid_segments=[dict(first=s[0],last=s[-1],frames=len(s)) for s in segments],
                rejected_branch_counts=failed_counts,relocalization_candidate_count_range=[min(candidates),max(candidates)] if candidates else None,
                transition_windows=windows,scope='Recorded decisions are evidence, not a proof of cause or performance improvement')
    output=Path(output)
    if output.exists():raise ValueError('Fresh diagnostic summary required')
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('folder','journal','output'):p.add_argument('--'+k,type=Path,required=True)
    r=summarize(**vars(p.parse_args()));print(json.dumps({k:r[k] for k in ('status','post_initialization_invalid_segments','rejected_branch_counts','relocalization_candidate_count_range')}))
