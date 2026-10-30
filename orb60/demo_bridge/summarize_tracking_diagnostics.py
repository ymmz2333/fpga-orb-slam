"""Summarize bounded per-frame RK diagnostics without inventing valid poses."""
import argparse
import collections
import json
import math
from pathlib import Path

def summarize(directory):
    paths=sorted(Path(directory).glob('tracking_diagnostics.part*.jsonl'))
    if not paths:raise ValueError('No instrumented tracking diagnostics found')
    stages=collections.Counter();transitions=[];loss_windows=[];window=collections.deque(maxlen=6)
    previous=None;rows=0;partial=0;dropped=0;last_pose=None;max_rotation=0.;histogram=[0]*32
    for path in paths:
        with path.open() as stream:
            for line in stream:
                try:row=json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith('\n'):partial+=1;continue
                    raise
                if row['schema']!=1:raise ValueError('Unknown diagnostic schema')
                rows+=1;dropped+=row['events_dropped'];events=row['events'];stages.update(e['stage'] for e in events)
                exit_events=[e for e in events if e['stage']=='tracking_exit']
                map_id=exit_events[-1]['map_id'] if exit_events else None
                if sum(row['levels'])!=row['features'] or sum(row['angle_bins'])!=row['features']:
                    raise ValueError('Diagnostic feature histogram mismatch')
                histogram=[a+b for a,b in zip(histogram,row['angle_bins'])]
                current=dict(frame=row['source_frame_id'],timestamp_ns=row['timestamp_ns'],map_id=map_id,state=row['tracking_state'],features=row['features'],events=events)
                if previous and (current['state']!=previous['state'] or current['map_id']!=previous['map_id']):
                    transitions.append(dict(frame=current['frame'],timestamp_ns=current['timestamp_ns'],from_state=previous['state'],to_state=current['state'],from_map=previous['map_id'],to_map=current['map_id']))
                    if previous['state']==2 and current['state']!=2:loss_windows.append(list(window)+[current])
                pose=row.get('tcw')
                if pose and last_pose and last_pose['map_id']==map_id:
                    product=sum(pose[4*r+c]*last_pose['pose'][4*r+c] for r in range(3) for c in range(3))
                    max_rotation=max(max_rotation,math.degrees(math.acos(max(-1.,min(1.,(product-1)/2)))))
                last_pose=dict(map_id=map_id,pose=pose) if pose else None
                window.append(current);previous=current
    return dict(schema=1,files=[p.name for p in paths],frames=rows,events_dropped=dropped,incomplete_tail_lines=partial,
                stage_calls=dict(stages),transitions=transitions,loss_windows=loss_windows,
                angle_histogram=histogram,max_adjacent_valid_rotation_deg=max_rotation,
                scope='Only retained diagnostic parts; estimated rotation is not ground truth. Missing matches/inliers are not inferred.')

def main():
    p=argparse.ArgumentParser();p.add_argument('tracking_directory',type=Path);a=p.parse_args();report=summarize(a.tracking_directory)
    path=a.tracking_directory/'tracking_diagnostics_summary.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('loss_windows','angle_histogram')},indent=2))
    print('SAVED',path)

if __name__=='__main__':main()
