"""Final 90-slot report; includes failures and stops for the user's layer choice."""
import argparse
import csv
import itertools
import json
import pathlib
import shutil
import statistics
import sys
import decimal
import bisect
from golden_audit_support import read_rows, atomic_json

def filter_ok_trajectory(raw, features, frames):
    """Recover source integer ns after the SLAM double-seconds export round trip.

    A 1 us bound is far below the frame interval. Require unique association;
    retain source timestamps rather than rounding an epoch timestamp again.
    """
    stamps=[int(f['timestamp_ns']) for f in features]
    if any(y<=x for x,y in zip(stamps,stamps[1:])):
        raise ValueError('Non-unique source timestamps')
    kept=[];seen={};kept_unique=set();maximum=0;excluded=0;duplicates=0;exported=0
    for line in raw.splitlines():
        fields=line.split()
        if not fields:continue
        stamp=int(decimal.Decimal(fields[0]).to_integral_value())
        i=bisect.bisect_left(stamps,stamp)
        candidates=[j for j in (i-1,i) if 0<=j<len(stamps)]
        j=min(candidates,key=lambda k:abs(stamps[k]-stamp))
        delta=abs(stamps[j]-stamp)
        if delta>1000:
            raise ValueError('Unmatched exported timestamp')
        if j in seen:
            if fields!=seen[j]:raise ValueError('Same source timestamp has different exported poses')
            duplicates+=1
        seen[j]=fields.copy();maximum=max(maximum,delta);exported+=1
        if frames[j]['state_after']=='2':
            fields[0]=str(stamps[j]);kept.append(' '.join(fields));kept_unique.add(j)
        else:excluded+=1
    return '\n'.join(kept)+'\n',dict(exported_rows=exported,unique_exported_frames=len(seen),
        identical_duplicate_export_rows=duplicates,kept_ok_rows=len(kept),kept_ok_unique_frames=len(kept_unique),
        excluded_non_ok_rows=excluded,max_export_rounding_ns=maximum,
        association_tolerance_ns=1000,method='nearest unique integer source ns; original raw unchanged')

def write(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row)) or ['status','reason']
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def frame_facts(raw,d,item,out):
    """Partial frame diagnostics do not require shutdown-only timing/map files."""
    frames=read_rows(raw/'TrackingStates.csv');features=read_rows(raw/'FeatureTimeStats.csv');maps=read_rows(raw/'MapStateStats.csv')
    if not (len(frames)==len(features)==len(maps)):raise ValueError('Diagnostic row alignment')
    if item['status']=='FINISHED' and len(frames)!=d['full_frames']:raise ValueError('Full frame count mismatch')
    for index,(s,f,m) in enumerate(zip(frames,features,maps)):
        if any(int(r['frame_index'])!=index for r in (s,f,m)):raise ValueError('Frame order')
        if float(int(f['timestamp_ns']))*1e-9!=float(s['timestamp_s']):raise ValueError('Timestamp association')
        if int(f['extractor_calls'])!=(1 if item['variant']=='native' else 0):raise ValueError('Extractor-call invariant')
    first=next((i for i,r in enumerate(frames) if r['state_after']=='2'),None)
    tail=frames[first+1:] if first is not None else []
    losses=[];i=first+1 if first is not None else len(frames)
    while i<len(frames):
        if frames[i]['state_after']=='2':i+=1;continue
        start=i
        while i<len(frames) and frames[i]['state_after']!='2':i+=1
        recovered=i<len(frames);stop=i if recovered else len(frames)-1
        losses.append(dict(start_frame=start,end_frame=i-1,frames=i-start,
            start_s=float(frames[start]['timestamp_s'])-float(frames[0]['timestamp_s']),
            end_s=float(frames[stop]['timestamp_s'])-float(frames[0]['timestamp_s']),
            duration_s=float(frames[stop]['timestamp_s'])-float(frames[start]['timestamp_s']),
            recovered=recovered,same_map=recovered and maps[start-1]['map_id']==maps[i]['map_id'],
            actual_relocalization=any(int(m['relocalized']) for m in maps[start:i+1]),
            end_is_censored=not recovered,scope='full sequence' if item['status']=='FINISHED' else 'completed frames only'))
    write(out/'loss_segments.csv',losses)
    inliers=[int(f['inliers']) for f,s in zip(features,frames) if s['state_after']=='2' and int(f['inliers'])>=0]
    result=dict(completed_frames=len(frames),frame_coverage=len(frames)/d['full_frames'],
        metric_scope='full sequence' if item['status']=='FINISHED' else 'partial; failed run retained',
        initialization_frame=first+1 if first is not None else None,
        initialization_time_s=float(frames[first]['timestamp_s'])-float(frames[0]['timestamp_s']) if first is not None else None,
        state_ok_frames=sum(r['state_after']=='2' for r in frames),lost_frames=sum(r['state_after'] in ('3','4') for r in frames),
        state_ok_fraction=sum(r['state_after']=='2' for r in frames)/len(frames) if frames else None,
        post_init_denominator=len(tail),post_init_ok_fraction=sum(r['state_after']=='2' for r in tail)/len(tail) if tail else None,
        loss_segments=len(losses),loss_duration_s=sum(r['duration_s'] for r in losses),
        inliers_median=statistics.median(inliers) if inliers else None,inliers_min=min(inliers,default=None),inliers_max=max(inliers,default=None),
        map_ids_observed=len({m['map_id'] for m in maps}),maps=None,
        inliers_mean=statistics.mean(inliers) if inliers else None,
        feature_count_mean=statistics.mean(int(f['count']) for f in features) if features else None,
        feature_count_median=statistics.median(int(f['count']) for f in features) if features else None,
        feature_count_ok_median=statistics.median(int(f['count']) for f,s in zip(features,frames) if s['state_after']=='2') if inliers else None)
    selected=raw/'SelectedPoints.csv'
    if selected.exists():
        layer_rows=read_rows(selected);level0=[int(r['selected']) for r in layer_rows if r['level']=='0']
        if len(level0)!=len(features):raise ValueError('SelectedPoints per-frame alignment')
        result['level0_selected_median']=statistics.median(level0) if level0 else None
    if item['status']=='FINISHED':
        final=read_rows(raw/'Diagnostics_maps.csv')
        result.update(maps=len(final),keyframes=sum(int(r['keyframes']) for r in final),map_points=sum(int(r['map_points']) for r in final))
    if d['kind']=='euroc':
        with (pathlib.Path(d['path'])/'mav0/state_groundtruth_estimate0/data.csv').open() as stream:
            truth=[int(r[0]) for r in csv.reader(stream) if r and not r[0].startswith('#')]
        trailing=[(s,f) for s,f in zip(frames,features) if int(f['timestamp_ns'])>truth[-1]]
        lost=[f for s,f in trailing if s['state_after'] in ('3','4')]
        result.update(outside_gt_tail_frames=len(trailing),outside_gt_tail_lost_frames=len(lost),tail_loss_first_ns=int(lost[0]['timestamp_ns']) if lost else None)
    atomic_json(out/'tracking_facts.json',result)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch-root',required=True);p.add_argument('--output',default='report');a=p.parse_args();batch=pathlib.Path(a.batch_root)
    sys.path.insert(0,str(batch/'source'))
    from analyze_c import analyze_run,read
    from evaluate_a2 import evaluate
    from finish_c import compare
    state=json.loads((batch/'batch_state.json').read_text())
    slots=state['schedule']
    keys={(r['dataset'],r['variant'],r['run_index']) for r in slots}
    if state['completed']!=90 or len(slots)!=90 or len(keys)!=90 or any(r['status'] not in ('FINISHED','FAILED') for r in slots):raise ValueError('Do not report an incomplete decision round')
    manifest=json.loads((batch/'configs/manifest.json').read_text());datasets={d['name']:d for d in manifest['datasets']}
    out=batch/a.output;out.mkdir(exist_ok=False);rows=[]
    for item in state['schedule']:
        d=datasets[item['dataset']];raw=batch/'runs'/item['folder'];row=dict(item,platform='x86 PC / WSL2',
            intrinsics=d['intrinsics_label'],initialization_frame=None,post_init_ok_fraction=None,loss_segments=None,maps=None,ate_rmse_m=None)
        folder=out/'analysis'/item['folder'];shutil.copytree(raw,folder)
        try:
            row.update(frame_facts(raw,d,item,folder))
        except Exception as error:
            if item['status']=='FINISHED':raise RuntimeError(item['folder']+' frame analysis failed: '+str(error)) from error
            row['partial_analysis_error']=str(error)
        if item['status']=='FINISHED':
            try:
                frames=read(folder/'TrackingStates.csv');first=next((i for i,f in enumerate(frames) if int(f['state_after'])==2),None)
                row.update(status='FINISHED' if first is not None else 'INITIALIZATION_FAILED')
                if d['kind']=='euroc' and first is not None:
                    # Analysis copy only: ATE includes OK poses, not RECENTLY_LOST poses.
                    trajectory=folder/'f_MH01.txt'
                    filtered,association=filter_ok_trajectory(trajectory.read_text(),read_rows(folder/'FeatureTimeStats.csv'),frames)
                    trajectory.write_text(filtered)
                    atomic_json(folder/'timestamp_association.json',association)
                    ate=evaluate(folder,pathlib.Path(d['path']));row.update(ate_rmse_m=ate['ate_rmse_m'],ate_method=ate['evaluation_method'],ate_associated=ate['associated_poses'])
                    row['ate_exported_ok_poses']=ate['exported_poses']
            except Exception as error:raise RuntimeError(item['folder']+' ATE analysis failed: '+str(error)) from error
        else:
            meta=raw/'run_metadata.json'
            if meta.exists():row['failure']=json.loads(meta.read_text()).get('failure_reason',item['status'])
            row['hang_snapshot']=str(raw/'hang_snapshot') if (raw/'hang_snapshot').exists() else None
        rows.append(row)
    write(out/'results.csv',rows);pairs=[]
    for name,d in datasets.items():
        groups={v:[r for r in rows if r['dataset']==name and r['variant']==v and r['status']=='FINISHED'] for v in manifest['plan']['variants']}
        if d['kind']!='prepared':continue
        for v,group in groups.items():
            candidates=[(x,y,'within_'+v) for x,y in itertools.combinations(group,2)]
            if v!='native':candidates += [(x,y,'native_vs_'+v) for x in groups['native'] for y in group]
            for x,y,kind in candidates:
                r=dict(dataset=name,variant=v,kind=kind,left=x['folder'],right=y['folder'],status='FAILED')
                try:r.update(compare(out/'analysis'/x['folder'],out/'analysis'/y['folder']),status='FINISHED')
                except Exception as error:r['error']=str(error)
                pairs.append(r)
    write(out/'native_differences.csv',pairs);summary=[]
    for name,d in datasets.items():
        native=[r for r in rows if r['dataset']==name and r['variant']=='native' and r['status']=='FINISHED']
        repeat=[r for r in pairs if r['dataset']==name and r['kind']=='within_native' and r['status']=='FINISHED']
        for variant in manifest['plan']['variants']:
            group=[r for r in rows if r['dataset']==name and r['variant']==variant];valid=[r for r in group if r['status']=='FINISHED']
            r=dict(dataset=name,variant=variant,attempts=len(group),valid=len(valid),failures=len(group)-len(valid))
            for field in ['initialization_frame','post_init_ok_fraction','loss_segments','loss_duration_s','maps','ate_rmse_m','inliers_median','feature_count_mean','feature_count_median','feature_count_ok_median','state_ok_fraction']:
                vals=[v[field] for v in valid if v[field] is not None];base=[v[field] for v in native if v[field] is not None]
                r[field+'_median']=statistics.median(vals) if vals else None;r[field+'_min']=min(vals) if vals else None;r[field+'_max']=max(vals) if vals else None
                r[field+'_native_min']=min(base) if base else None;r[field+'_native_max']=max(base) if base else None
                r[field+'_native_difference_min']=min(x-y for x in vals for y in base) if vals and base else None
                r[field+'_native_difference_max']=max(x-y for x in vals for y in base) if vals and base else None
            cross=[v for v in pairs if v['dataset']==name and v['kind']=='native_vs_'+variant and v['status']=='FINISHED']
            r['normalized_shape_difference_min']=min([v['normalized_rms'] for v in cross],default=None)
            r['normalized_shape_difference_max']=max([v['normalized_rms'] for v in cross],default=None)
            r['native_repeatability_max']=max([v['normalized_rms'] for v in repeat],default=None)
            r['common_ok_coverage_min']=min([v['input_coverage'] for v in cross],default=None)
            # Report coverage; no automatic qualitative equivalence claim from low/partial overlap.
            r['coverage_sufficient']=bool(cross and repeat and len(valid)==5 and len(native)==5 and min(v['input_coverage'] for v in cross)>=0.9 and min(v['input_coverage'] for v in repeat)>=0.9)
            r['coverage_rule']='conservative reporting screen: all pairs >=90%; not an accuracy threshold'
            summary.append(r)
    write(out/'summary_by_layers.csv',summary)
    text='# '+state.get('report_title','B3 G1层数决策轮')+'完成\n\n平台：x86 PC / WSL2。Tello：借用内参，未本机标定。耗时不作性能结论。\n\n'
    text+='90个原始槽位全部保留，失败不替换。results.csv包含初始化帧、初始化后OK、丢失段、地图、MH01 ATE；summary_by_layers.csv给出中位/范围和native差异范围。\n\n'
    text+='卡死槽位保留完成帧范围内的状态、内点和丢失片段（末端删失）；最终地图数与ATE未完成时留空。汇总中位数仅取成功且完成全序列的运行，并列出失败数。MH01 ATE仅关联OK位姿，evo与NumPy逐点校核。\n\n'
    text+='V0为G1关闭F/G/A32的定点控制，非历史原版字节等价注入控制。低公共OK覆盖时不得宣布无可测差异。Tello归一化Sim3形状差异不等于ATE或真实尺度。\n\n'
    text+='本轮在这里停下，等待用户选择层数，再更新规范v1.0；不自动启动其他矩阵或上板实验。\n'
    (out/'REPORT.md').write_text(text)
    print('DECISION_REPORT_READY_WAIT_USER',out)
if __name__=='__main__':main()
