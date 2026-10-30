#!/usr/bin/env python3
"""State-aligned B1 measurements; feature slot is I/O in inject, not ORB extraction."""
import csv
import json
import math
import pathlib
import statistics
from analyze_a2 import analyze, describe

def analyze_features(folder,dataset,mode,expected_frames=3682):
    folder=pathlib.Path(folder); dataset=pathlib.Path(dataset)
    facts=analyze(folder,expected_frames=expected_frames)
    with (folder/'frames.csv').open() as f: frames=list(csv.DictReader(f))
    with (folder/'FeatureTimeStats.csv').open() as f: features=list(csv.DictReader(f))
    if len(features)!=len(frames): raise RuntimeError('Feature/state timing row mismatch')
    with (dataset/'mav0/state_groundtruth_estimate0/data.csv').open() as f:
        truth=[int(row[0]) for row in csv.reader(f) if row and not row[0].startswith('#')]
    gt_start,gt_end=min(truth),max(truth)
    rows=[]
    for index,(frame,feature) in enumerate(zip(frames,features)):
        if int(feature['frame_index'])!=index or abs(int(feature['timestamp_ns'])/1e9-float(frame['timestamp_s']))>0.000001:
            raise RuntimeError('Exact feature timestamp is not aligned with tracking row')
        if int(feature['extractor_calls'])!={'native':1,'inject':0,'dump':2}[mode]:
            raise RuntimeError('Unexpected extractor call in '+mode)
        numbers={key:float(feature[key]) for key in ('read_ms','decode_ms','native_ms','dump_ms','auxiliary_ms')}
        if not all(math.isfinite(v) and v>=0 for v in numbers.values()): raise RuntimeError('Invalid feature timing')
        total=float(frame['total_ms']); slot=float(frame['orb_ms'])
        if numbers['read_ms']+numbers['decode_ms']>slot+0.002 or numbers['native_ms']>slot+0.002:
            raise RuntimeError('Nested feature timing exceeds enclosing feature slot')
        if mode=='inject' and numbers['native_ms']!=0: raise RuntimeError('Inject executed ORB')
        rows.append(dict(frame_index=index,timestamp_ns=feature['timestamp_ns'],category=frame['category'],
                         total_ms=total,feature_slot_ms=slot,remaining_ms=total-slot,inliers=int(feature['inliers']),
                         gt_covered=gt_start<=int(feature['timestamp_ns'])<=gt_end,**numbers))
    with (folder/'b1_frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    summary=[]
    for category in ('normal','initialization','lost'):
        selected=[r for r in rows if r['category']==category]
        for metric in ('total_ms','feature_slot_ms','remaining_ms','read_ms','decode_ms','native_ms'):
            summary.append(dict(category=category,metric=metric,**describe([r[metric] for r in selected])))
    with (folder/'b1_timing_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0])); w.writeheader(); w.writerows(summary)
    normal=[r for r in rows if r['category']=='normal']
    result=dict(mode=mode,tracking_width=752,tracking_height=480,nFeatures=1000,nLevels=8,initialization_nFeatures=5000,
                normal_frames=facts['frames'],lost_frames=facts['lost_frames'],initialization_frames=facts['initialization_frames'],
                maps=facts['maps'],processed_frames=facts['processed_frames'],state_ok_frames=sum(int(f['state_after'])==2 for f in frames),
                state_ok_fraction=sum(int(f['state_after'])==2 for f in frames)/len(frames),
                recovery_frames=facts['recovery_frames'],active_map_resets=facts['active_map_resets'],full_resets=facts['full_resets'],
                gt_input_frames=sum(r['gt_covered'] for r in rows),
                gt_ok_frames=sum(r['gt_covered'] and int(f['state_after'])==2 for r,f in zip(rows,frames)),
                tail_lost_frames=sum(r['category']=='lost' and int(r['timestamp_ns'])>gt_end for r in rows),
                gt_lost_frames=sum(r['category']=='lost' and r['gt_covered'] for r in rows),
                last_state=int(frames[-1]['state_after']),first_tail_loss_ns=next((r['timestamp_ns'] for r in rows if r['category']=='lost' and int(r['timestamp_ns'])>gt_end),''),
                tracking_total_mean_ms=facts['total_mean_ms'],tracking_total_median_ms=facts['total_median_ms'],tracking_total_p95_ms=facts['total_p95_ms'],
                orb_slot_semantics='file_read_decode' if mode=='inject' else 'ORB_algorithm',
                orb_ratio_frame_median=facts['orb_ratio_frame_median'] if mode=='native' else '',
                orb_ratio_sums=facts['orb_ratio_sums'] if mode=='native' else '',
                total_gt33_fraction=facts['total_gt33_fraction'],total_gt50_fraction=facts['total_gt50_fraction'])
    for metric in ('remaining_ms','read_ms','decode_ms','native_ms','feature_slot_ms'):
        values=describe([r[metric] for r in normal])
        for stat in ('median','mean','p95'): result[metric+'_'+stat]=values[stat]
    valid_inliers=[r['inliers'] for r in normal if r['inliers']>=0]
    result['inliers_mean']=statistics.mean(valid_inliers) if valid_inliers else ''
    result['inliers_median']=statistics.median(valid_inliers) if valid_inliers else ''
    result['inliers_valid_frames']=len(valid_inliers)
    (folder/'b1_facts.json').write_text(json.dumps(result,indent=2))
    return result
