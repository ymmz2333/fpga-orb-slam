"""H1 original/new ranges, H2 feature medians and frame-145 control-flow evidence."""
import argparse,csv,json,pathlib,statistics
from golden_audit_support import read_rows,atomic_json
from finish_c import compare
def write(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)),lineterminator='\n');w.writeheader();w.writerows(rows)
def main():
    p=argparse.ArgumentParser();p.add_argument('--batch-root',required=True,type=pathlib.Path);a=p.parse_args();batch=a.batch_root;out=batch/'report'
    old=batch.parent/'G1_layers_resume_20261006_013559';prior=read_rows(old/'report_corrected/results.csv');current=read_rows(out/'results.csv');ranges=[];shapes=[];near=[]
    for dataset in sorted({r['dataset'] for r in current}):
        for variant in ['native','V0']:
            before=[r for r in prior if r['dataset']==dataset and r['variant']==variant and r['status']=='FINISHED'];after=[r for r in current if r['dataset']==dataset and r['variant']==variant and r['status']=='FINISHED']
            for field in ['initialization_frame','post_init_ok_fraction','loss_segments','maps','inliers_median','ate_rmse_m','state_ok_fraction']:
                b=[float(r[field]) for r in before if r.get(field,'')!=''];n=[float(r[field]) for r in after if r.get(field,'')!='']
                if not b or not n:continue
                ranges.append(dict(dataset=dataset,variant=variant,metric=field,old_valid=len(before),new_valid=len(after),old_median=statistics.median(b),old_min=min(b),old_max=max(b),new_median=statistics.median(n),new_min=min(n),new_max=max(n),all_new_within_old_observed_range=min(n)>=min(b) and max(n)<=max(b),scope='observed five-repeat ranges, not significance test; old MH01 native has 4 valid runs'))
            if dataset!='MH01':
                for b in before:
                    for n in after:
                        r=dict(dataset=dataset,variant=variant,before=b['folder'],after=n['folder'],status='FAILED')
                        try:r.update(compare(old/'report_corrected/analysis'/b['folder'],out/'analysis'/n['folder']),status='FINISHED')
                        except Exception as e:r['reason']=str(e)
                        shapes.append(r)
    write(out/'H1_previous_ranges.csv',ranges);write(out/'H1_old_new_shapes.csv',shapes)
    dataset='flight_20261004T200648_509768_918b85a4'
    for r in current:
        if r['dataset']==dataset and r['variant']=='L8':
            raw=batch/'runs'/r['folder'];states=read_rows(raw/'TrackingStates.csv');maps=read_rows(raw/'MapStateStats.csv')
            for s,m in zip(states[135:170],maps[135:170]):near.append(dict(run_index=r['run_index'],**s,**{k:v for k,v in m.items() if k not in s}))
    write(out/'H1_L8_frame145.csv',near)
    counts=[]
    for r in current:
        raw=batch/'runs'/r['folder'];features=read_rows(raw/'FeatureTimeStats.csv');selected=read_rows(raw/'SelectedPoints.csv')
        per={}
        for s in selected:
            key=(s['timestamp_ns'],s['role']);per.setdefault(key,[]).append(s)
        for role in ['0','1']:
            fs=[f for f in features if f['role']==role];zero=[];total=[]
            for f in fs:
                ls=per[f['timestamp_ns'],role];n=sum(int(s['selected']) for s in ls)
                if n!=int(f['count']):raise ValueError('Observed selected count does not match in-memory total')
                total.append(n);zero.append(int(next(s for s in ls if s['level']=='0')['selected']))
            counts.append(dict(dataset=r['dataset'],variant=r['variant'],run_index=r['run_index'],role=role,frames=len(fs),status=r['status'],scope=r['metric_scope'],level0_selected_median=statistics.median(zero) if zero else '',all_selected_median=statistics.median(total) if total else '',requested_total_budget=5000 if role=='1' else 1000))
    write(out/'H2_selected_per_run.csv',counts)
    summaries=[]
    for key in sorted({(r['dataset'],r['variant'],r['role']) for r in counts}):
        group=[r for r in counts if (r['dataset'],r['variant'],r['role'])==key and r['status']=='FINISHED'];s=dict(dataset=key[0],variant=key[1],role=key[2],completed_runs=len(group))
        for field in ['level0_selected_median','all_selected_median']:
            vals=[r[field] for r in group if r[field]!=''];s[field+'_median_over_runs']=statistics.median(vals) if vals else '';s[field+'_min']=min(vals) if vals else '';s[field+'_max']=max(vals) if vals else ''
        summaries.append(s)
    write(out/'H2_selected_summary.csv',summaries)
    failures=[r for r in current if r['status'] not in ['FINISHED','INITIALIZATION_FAILED']]
    atomic_json(out/'acceptance.json',dict(status='COMPLETED_AWAIT_USER_DECISION',formal_slots=len(current),failures=len(failures),H1_ranges_outside=sum(not r['all_new_within_old_observed_range'] for r in ranges),parameters_changed=False,platform='x86 PC / WSL2',performance_conclusions=False))
    with (out/'REPORT.md').open('a') as f:f.write('\nH1修复：Refine成功提前返回前同步bNoMore=(mnIterations>=mRansacMaxIts)，未改变RANSAC参数、匹配阈值、循环条件或随机种子。诊断见diagnosis.json；H1_previous_ranges.csv逐项标出新结果是否在旧观察范围内，超出范围不自动等同算法变化，须结合重复性和H1_old_new_shapes.csv说明。\n\nH1_L8_frame145.csv保存五次修复后135–169零基帧状态；SelectedPoints.csv为实际使用特征的逐层计数。H2_selected_summary.csv为五次每帧点数中位数的中位数/最小/最大，两档分开。历史统计见../historical_selected/；native历史逐层数为核对历史总数后的重建，不伪称历史逐层实测。\n\n规范交付v0.95；最多8层、可配置、scaleFactor1.2已冻结，最终默认层数由用户决定。此轮停下，不自动更新v1.0。\n')
    print('H1_H2_REPORT_READY_STOP',flush=True)
if __name__=='__main__':main()
