#!/usr/bin/env python3
"""Read-only A3 timing anomaly and terminal tracking-loss analysis."""
import csv
import json
import pathlib
import statistics
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parent.parent
RAW=ROOT/'reports/a3/MH01_matrix_passive_01/raw'
OUT=ROOT/'reports/b0'; OUT.mkdir(parents=True,exist_ok=True)
TARGETS={'baseline_752x480':4,'half_376x240':1,'features_1500':5,'levels_4':2,'levels_1':3}
GT=np.loadtxt(ROOT/'reports/a2/MH01_600x350_passive_01/raw/groundtruth_cam0.tum')
names={'ORB':2,'Pose prediction':5,'Local map':6,'Keyframe decision':7,'Total':8}
comparisons=[]
for config,target in TARGETS.items():
    runs={}
    for run in range(1,6):
        folder=RAW/('%s_run%02d'%(config,run))
        with (folder/'TrackingStates.csv').open() as stream: states=list(csv.DictReader(stream))
        times=np.loadtxt(folder/'TrackingTimeStats.txt',delimiter=',',comments='#')
        normal=np.array([int(s['state_before']) in (2,3,4) and int(s['state_after'])==2 for s in states])
        stamps=np.array([float(s['timestamp_s']) for s in states])
        runs[run]=(times,normal,(stamps>=GT[0,0]) & (stamps<=GT[-1,0]))
    common=np.logical_and.reduce([normal & inside for times,normal,inside in runs.values()])
    for selection in ('normal','common_GT_frames'):
        for module,column in dict(names,**{'Total minus ORB':None}).items():
            medians=[]
            for run,(times,normal,inside) in runs.items():
                mask=normal if selection=='normal' else common
                values=times[mask,column] if column is not None else times[mask,8]-times[mask,2]
                if column is not None: values=values[values>0]
                medians.append(float(np.median(values)))
            faster=medians[target-1]; peers=statistics.median(v for i,v in enumerate(medians,1) if i!=target)
            comparisons.append(dict(configuration=config,fast_run=target,selection=selection,module=module,
                                    fast_median_ms=faster,other_four_median_ms=peers,
                                    delta_ms=faster-peers,delta_percent=100*(faster/peers-1),
                                    common_frames=int(common.sum())))
with (OUT/'timing_comparison.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(comparisons[0])); writer.writeheader(); writer.writerows(comparisons)
timestamps=[int(s) for s in (ROOT/'reports/a2/MH01.txt').read_text().splitlines() if s.strip()]
losses=[]
for run in range(1,6):
    with (RAW/('levels_1_run%02d'%run)/'TrackingStates.csv').open() as stream: states=list(csv.DictReader(stream))
    indices=[i for i,s in enumerate(states) if int(s['state_after']) in (3,4)]
    groups=[]
    for index in indices:
        if not groups or index!=groups[-1][-1]+1: groups.append([])
        groups[-1].append(index)
    for segment,group in enumerate(groups,1):
        begin,end=group[0],group[-1]
        losses.append(dict(run_index=run,segment=segment,first_frame_index=begin,last_frame_index=end,
                           first_timestamp_ns=timestamps[begin],last_timestamp_ns=timestamps[end],
                           first_elapsed_s=(timestamps[begin]-timestamps[0])/1e9,last_elapsed_s=(timestamps[end]-timestamps[0])/1e9,
                           lost_frames=len(group),persists_to_end=end==len(states)-1,
                           GT_covered_frames=int(sum(GT[0,0]<=timestamps[i]/1e9<=GT[-1,0] for i in group))))
with (OUT/'levels1_tail_loss.csv').open('w',newline='',encoding='utf-8') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(losses[0])); writer.writeheader(); writer.writerows(losses)
print('B0_READ_ONLY_ANALYSIS_READY')
for row in comparisons:
    if row['selection']=='common_GT_frames':
        print('%s #%d | %s %.3f vs %.3f ms (%+.1f%%)'%(row['configuration'],row['fast_run'],row['module'],row['fast_median_ms'],row['other_four_median_ms'],row['delta_percent']))
print(json.dumps(losses))
