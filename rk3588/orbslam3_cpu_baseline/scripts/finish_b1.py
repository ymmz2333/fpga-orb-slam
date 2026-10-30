#!/usr/bin/env python3
"""User-triggered PC collection/evo evaluation, excludes multi-GB corpus from transfer."""
import argparse
import csv
import json
import pathlib
import re
import shutil
import statistics
import subprocess
import traceback
from analyze_b1 import analyze_features
from evaluate_a2 import evaluate

ROOT=pathlib.Path(__file__).resolve().parent.parent

def summary(report):
    with (report/'results_exp3_b1.csv').open(encoding='utf-8') as f: rows=list(csv.DictReader(f))
    metrics=('ate_rmse_m','normal_frames','lost_frames','tail_lost_frames','maps','state_ok_fraction','tracking_total_mean_ms','tracking_total_median_ms',
             'tracking_total_p95_ms','remaining_ms_median','remaining_ms_p95','read_ms_median','decode_ms_median',
             'inliers_mean','orb_ratio_frame_median','orb_ratio_sums','initialization_frames','total_gt33_fraction','total_gt50_fraction',
             'mean_soc_temp_c','max_soc_temp_c','read_ms_p95','decode_ms_p95','feature_slot_ms_median','feature_slot_ms_p95')
    output=[]
    for mode in ('native','inject'):
        group=[r for r in rows if r['mode']==mode and r['valid']=='True']
        for metric in metrics:
            values=[float(r[metric]) for r in group if r.get(metric,'')!='']
            output.append(dict(mode=mode,configuration='752x480_1000_8_fixed_DDR',valid_runs=len(group),metric=metric,
                               median=statistics.median(values) if values else '',min=min(values) if values else '',max=max(values) if values else ''))
    with (report/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0])); w.writeheader(); w.writerows(output)
    comparison=[]
    for mode in ('native','inject'):
        group=[r for r in rows if r['mode']==mode and r['valid']=='True']
        def med(key):
            values=[float(r[key]) for r in group if r.get(key,'')!='']
            return statistics.median(values) if values else ''
        comparison.append(dict(condition='B1_'+mode,ddr='performance_1560MHz',tracking_width=752,tracking_height=480,
                               valid_runs=len(group),total_ms=med('tracking_total_median_ms'),
                               remaining_ms=med('remaining_ms_median'),orb_ms=med('native_ms_median') if mode=='native' else '',
                               file_read_ms=med('read_ms_median'),decode_ms=med('decode_ms_median'),
                               orb_ratio_sums=med('orb_ratio_sums')))
    a3=ROOT/'reports/a3/MH01_matrix_passive_01/results_exp1.csv'
    with a3.open(encoding='utf-8') as f:
        old=[r for r in csv.DictReader(f) if r['stage']=='A3' and r['configuration']=='baseline_752x480' and r['tracking_result_valid']=='True']
    comparison.append(dict(condition='A3_accepted_baseline_reference',ddr='dynamic_unrecorded',tracking_width=752,tracking_height=480,
        valid_runs=len(old),total_ms=statistics.median(float(r['total_median_ms']) for r in old),remaining_ms='',
        orb_ms=statistics.median(float(r['orb_median_ms']) for r in old),file_read_ms='',decode_ms='',
        orb_ratio_sums=statistics.median(float(r['orb_ratio_sums']) for r in old)))
    with (report/'baseline_comparison.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(comparison[0])); w.writeheader(); w.writerows(comparison)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); p.add_argument('--dataset',required=True)
    p.add_argument('--local-only',action='store_true'); p.add_argument('--csv-only',action='store_true'); a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch): raise SystemExit('Invalid batch ID')
    report=ROOT/'reports/b1'/a.batch; source=ROOT/'runtime/b1'/a.batch
    if a.csv_only: summary(report); return
    source.mkdir(parents=True,exist_ok=True)
    if not a.local_only:
        board=json.loads((ROOT/'local_board.json').read_text(encoding='utf-8')); alias=board.get('sshAlias','rk3588')
        remote=board.get('remoteRoot','~/orbslam3_cpu_baseline')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',alias) or alias.startswith('-') or not re.fullmatch(r'(~/|/)[A-Za-z0-9_./-]+',remote):
            raise SystemExit('Invalid remote alias/root')
        base=alias+':'+remote+'/runtime/b1/'+a.batch+'/'
        subprocess.run(['scp','-q',base+'batch_state.json',str(source/'batch_state.json')],check=True)
        state=json.loads((source/'batch_state.json').read_text(encoding='utf-8'))
        if state['status']=='RUNNING': raise SystemExit('Batch still running; no log polling or live file evaluation')
        # Transfer only completed/present attempts and verification, never corpus or snapshots.
        for item in [state.get('dump',{})]+state['schedule']:
            if item.get('status'):
                subprocess.run(['scp','-q','-r',base+item['folder'],str(source)],check=True)
        if state.get('verification'): subprocess.run(['scp','-q','-r',base+'verification',str(source)],check=True)
        subprocess.run(['scp','-q',base+'raw_manifest.csv',str(source/'raw_manifest.csv')],check=True)
    state=json.loads((source/'batch_state.json').read_text(encoding='utf-8'))
    if state['status']=='RUNNING': raise SystemExit('Batch still running')
    report.mkdir(parents=True,exist_ok=True); shutil.copy2(source/'batch_state.json',report/'batch_state.json')
    if (source/'raw_manifest.csv').exists(): shutil.copy2(source/'raw_manifest.csv',report/'raw_manifest.csv')
    if (source/'verification').exists(): shutil.copytree(source/'verification',report/'verification',dirs_exist_ok=True)
    if state.get('dump') and (source/state['dump']['folder']).exists():
        shutil.copytree(source/state['dump']['folder'],report/'raw'/state['dump']['folder'],dirs_exist_ok=True)
    rows=[]
    for item in state['schedule']:
        folder=source/item['folder']; row=dict(mode=item['mode'],run_index=item['run_index'],valid=False,
                                              finished_input=False,status='未完成',reason='尚未执行',ate_rmse_m='')
        if (folder/'run_metadata.json').exists():
            meta=json.loads((folder/'run_metadata.json').read_text(encoding='utf-8')); errors=[]
            row.update(process_status=meta['status'],cpu_drop=meta['frequency_drop_detected'],
                       dmc_drop=meta.get('dmc_frequency_drop',False),thermal_cap=meta['thermal_cap_detected'],
                       dmc_restored=meta.get('dmc_restored',False),cpu_restored=meta.get('governors_restored',False))
            with (folder/'telemetry.csv').open() as stream:
                samples=list(csv.DictReader(stream))
            row['mean_soc_temp_c']=statistics.mean(float(s['thermal_zone0_temp_mc'])/1000 for s in samples)
            row['max_soc_temp_c']=max(float(s['thermal_zone0_temp_mc'])/1000 for s in samples)
            for name in ('policy4_cur_khz','policy6_cur_khz','dmc_cur_hz'):
                values=[int(s[name]) for s in samples]
                row[name+'_min']=min(values); row[name+'_max']=max(values)
            if meta['status']=='FINISHED':
                try: row.update(analyze_features(folder,a.dataset,item['mode']))
                except Exception as error: errors.append('Timing: '+str(error)); (folder/'evaluation.log').write_text(traceback.format_exc())
                try: row.update(evaluate(folder,a.dataset))
                except Exception as error:
                    errors.append('ATE: '+str(error))
                    with (folder/'evaluation.log').open('a') as f: f.write(traceback.format_exc())
            else: errors.append(meta.get('error') or 'SLAM process failed')
            row['finished_input']=meta['status']=='FINISHED' and row.get('processed_frames')==3682
            row['valid']=row['finished_input'] and not errors and not (row['cpu_drop'] or row['dmc_drop'] or row['thermal_cap']) and row['dmc_restored'] and row['cpu_restored']
            row.update(status='完成' if row['valid'] else '未完成',reason='; '.join(errors))
            # All retained raw outputs, with derived files alongside; no feature corpus duplication.
            shutil.copytree(folder,report/'raw'/item['folder'],dirs_exist_ok=True)
        rows.append(row)
        if item.get('status'): print('%s #%s | 跑完=%s | ATE=%s m | 降频=%s'%(row['mode'],row['run_index'],row['finished_input'],row['ate_rmse_m'] or '未完成',row.get('cpu_drop',False) or row.get('dmc_drop',False) or row.get('thermal_cap',False)))
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (report/'results_exp3_b1.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    summary(report)

if __name__=='__main__': main()
