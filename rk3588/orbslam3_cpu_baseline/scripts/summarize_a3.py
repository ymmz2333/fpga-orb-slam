#!/usr/bin/env python3
"""Build results_exp1.csv and median/min/max summary solely from retained raw facts."""
import argparse
import csv
import json
import pathlib
import statistics
import math

ROOT=pathlib.Path(__file__).resolve().parent.parent
METRICS=['ate_rmse_m','total_mean_ms','total_median_ms','total_p95_ms','orb_median_ms','orb_p95_ms',
         'orb_ratio_frame_median','orb_ratio_sums','total_gt50_fraction','total_gt33_fraction','mean_soc_temp_c']

def summarize(report):
    state=json.loads((report/'batch_state.json').read_text(encoding='utf-8'))
    records=[]
    for item in state['schedule']:
        folder=report/'raw'/item['folder']
        row=dict(stage='A3',**{k:v for k,v in item.items() if k not in ('effective_intrinsics','observed_intrinsics')},
                 finished_input=False,tracking_result_valid=False,status='未完成',reason='尚未执行')
        if (folder/'run_metadata.json').exists():
            meta=json.loads((folder/'run_metadata.json').read_text(encoding='utf-8'))
            row.update(process_status=meta['status'],exit_code=meta['exit_code'],
                       frequency_drop=meta['frequency_drop_detected'],thermal_cap=meta['thermal_cap_detected'],
                       governors_restored=meta.get('governors_restored',False),reason=meta.get('error',''))
            for filename in ('timing_facts.json','ate.json'):
                if (folder/filename).exists(): row.update(json.loads((folder/filename).read_text(encoding='utf-8')))
            evaluation=json.loads((folder/'evaluation.json').read_text(encoding='utf-8')) if (folder/'evaluation.json').exists() else {}
            row['finished_input']=meta['status']=='FINISHED' and row.get('processed_frames')==3682
            row['tracking_result_valid']=(row['finished_input'] and evaluation.get('status')=='PASS'
                                          and row.get('ate_rmse_m') is not None
                                          and math.isfinite(row['ate_rmse_m']) and row.get('frames',0)>0)
            row['status']='完成' if row['tracking_result_valid'] else '未完成'
            row['reason']=row['reason'] or evaluation.get('reason','')
            if row.get('frames')==0: row['reason']='初始化失败：全程没有正常跟踪帧'
            if row['frequency_drop'] or row['thermal_cap']:
                row.update(status='降频，批次暂停',tracking_result_valid=False)
            telemetry=folder/'telemetry.csv'
            if telemetry.exists():
                with telemetry.open() as stream: samples=list(csv.DictReader(stream))
                temps=[float(s['thermal_zone0_temp_mc'])/1000 for s in samples]
                row['mean_soc_temp_c']=statistics.mean(temps) if temps else ''
                row['max_soc_temp_c']=max(temps) if temps else ''
                row['max_all_zones_temp_c']=max((float(v)/1000 for s in samples for k,v in s.items() if k.endswith('_temp_mc')),default='')
                for policy in ('policy4','policy6'):
                    values=[int(s[policy+'_cur_khz']) for s in samples]
                    row[policy+'_freq_min_khz']=min(values) if values else ''
                    row[policy+'_freq_max_khz']=max(values) if values else ''
        records.append(row)
    with (ROOT/'reports/a2/MH01_600x350_passive_01/runs.csv').open(encoding='utf-8') as stream:
        for original in csv.DictReader(stream):
            original.update(stage='A2 reference',configuration='official_600x350_reference',tracking_width=600,tracking_height=350,
                            resize_policy='official nonuniform resize',run_index=int(original['attempt'].split('_')[1]),
                            nFeatures=1000,nLevels=8,initialization_nFeatures=5000,
                            finished_input=True,tracking_result_valid=True)
            records.append(original)
    fields=list(dict.fromkeys(k for row in records for k in row))
    with (report/'results_exp1.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(records)
    summarize_csv(report)
    return records

def summarize_csv(report):
    with (report/'results_exp1.csv').open(encoding='utf-8') as stream:
        records=list(csv.DictReader(stream))
    summary=[]
    for name in dict.fromkeys(r['configuration'] for r in records):
        group=[r for r in records if r['configuration']==name]
        valid=[r for r in group if r['tracking_result_valid']=='True']
        for metric in METRICS:
            values=[float(r[metric]) for r in valid if r.get(metric,'')!='']
            summary.append(dict(configuration=name,stage=group[0]['stage'],tracking_width=group[0]['tracking_width'],
                                tracking_height=group[0]['tracking_height'],resize_policy=group[0]['resize_policy'],
                                planned_runs=len(group),valid_runs=len(valid),metric=metric,
                                median=statistics.median(values) if values else '',min=min(values) if values else '',max=max(values) if values else ''))
    with (report/'summary.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summary[0])); writer.writeheader(); writer.writerows(summary)
    return records

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('report',type=pathlib.Path)
    parser.add_argument('--csv-only',action='store_true'); args=parser.parse_args()
    rows=summarize_csv(args.report) if args.csv_only else summarize(args.report)
    for row in rows:
        if row['stage']!='A3' or row['reason']=='尚未执行': continue
        print('%s #%s | 跑完=%s | ATE=%s m | 降频=%s'%(row['configuration'],row['run_index'],row['finished_input'],row.get('ate_rmse_m','未完成'),row.get('frequency_drop',False) or row.get('thermal_cap',False)))
