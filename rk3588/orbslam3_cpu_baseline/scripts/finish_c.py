"""User-triggered PC collection and no-ground-truth report; refuse running batches."""
import argparse,csv,decimal,itertools,json,pathlib,shutil,statistics,subprocess
import numpy as np
from analyze_c import analyze_run,read,write
from evaluate_a2 import umeyama
ROOT=pathlib.Path(__file__).resolve().parents[1]
def trajectory(folder):
    maps=read(folder/'Diagnostics_maps.csv')
    chosen=max(maps,key=lambda r:int(r['keyframes']))
    if not chosen['trajectory_file']: raise ValueError('No initialized trajectory')
    states=read(folder/'TrackingStates.csv'); ok=np.array([float(r['timestamp_s']) for r in states if r['state_after']=='2'])
    points={}
    for line in (folder/pathlib.Path(chosen['trajectory_file']).name).read_text(encoding='utf-8').splitlines():
        fields=line.split()
        if len(fields)!=8: continue
        ns=int(decimal.Decimal(fields[0]).to_integral_value()); stamp=ns/1e9
        if len(ok) and np.min(np.abs(ok-stamp))<1e-7: points[ns]=np.array(list(map(float,fields[1:4])))
    return points,len(states),chosen['map_id']
def compare(a,b):
    left,total,mapid=trajectory(a); right,_,other=trajectory(b); common=sorted(left.keys() & right.keys())
    if len(common)<3: raise ValueError('Insufficient paired OK frames')
    reference=np.array([left[n] for n in common]); estimate=np.array([right[n] for n in common])
    transform,errors=umeyama(reference,estimate)
    spread=float(np.sqrt(np.mean(np.sum((reference-reference.mean(axis=0))**2,axis=1))))
    return dict(common_ok_frames=len(common),input_coverage=len(common)/total,reference_map=mapid,estimate_map=other,
        rms_reference_slam_units=float(np.sqrt(np.mean(errors**2))),normalized_rms=float(np.sqrt(np.mean(errors**2)))/spread,
        sim3_scale=transform['scale'],units='arbitrary reference SLAM units; normalized RMS dimensionless; not ATE')
def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(); p.add_argument('--batch',required=True); p.add_argument('--download',action='store_true'); a=p.parse_args()
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch): raise ValueError('Invalid batch ID')
    runtime=ROOT/'runtime/c'/a.batch; runtime.mkdir(parents=True,exist_ok=True)
    if a.download:
        board=json.loads((ROOT/'local_board.json').read_text(encoding='utf-8')); remote=board.get('remoteRoot','~/orbslam3_cpu_baseline')
        base=board.get('sshAlias','rk3588')+':'+remote+'/runtime/c/'+a.batch+'/'
        subprocess.run(['scp','-q',base+'batch_state.json',str(runtime/'batch_state.json')],check=True)
        state=json.loads((runtime/'batch_state.json').read_text(encoding='utf-8'))
        if state['status']=='RUNNING': raise SystemExit('Still running; no log polling')
        for item in state['schedule']:
            if item.get('status'): subprocess.run(['scp','-q','-r',base+item['folder'],str(runtime)],check=True)
        if state['status']=='FINISHED':
            subprocess.run(['scp','-q',base+'raw_manifest.csv',str(runtime)],check=True)
            subprocess.run(['scp','-q',base+'batch.log',str(runtime)],check=True)
    state=json.loads((runtime/'batch_state.json').read_text(encoding='utf-8'))
    if state['status']=='RUNNING': raise SystemExit('Still running')
    report=ROOT/'reports/c2'/a.batch; report.mkdir(parents=True,exist_ok=True); results=[]
    if (runtime/'raw_manifest.csv').exists():
        import hashlib
        for r in read(runtime/'raw_manifest.csv'):
            path=runtime/r['path']
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=r['sha256']: raise ValueError('Transport hash mismatch '+r['path'])
        shutil.copy2(runtime/'raw_manifest.csv',report/'raw_manifest.csv')
    # Preserve downloaded evidence byte-for-byte. Analysis writes derived CSVs
    # into a separate tree, so the raw SHA256 manifest remains valid afterward.
    shutil.copytree(runtime,report/'raw',dirs_exist_ok=True)
    for item in state['schedule']:
        folder=runtime/item['folder']; row=dict(clip=item['clip'],configuration=item['configuration'],run_index=item['run_index'],
            finished_input=False,valid=False,status='未完成',reason='尚未执行',ate_rmse_m='',intrinsics_label='临时内参，待标定后重跑')
        if (folder/'run_metadata.json').exists():
            m=json.loads((folder/'run_metadata.json').read_text(encoding='utf-8')); row.update(process_status=m['status'],
                cpu_drop=m['frequency_drop_detected'],dmc_drop=m.get('dmc_frequency_drop',False),thermal_cap=m['thermal_cap_detected'],
                cpu_restored=m.get('governors_restored',False),dmc_restored=m.get('dmc_restored',False))
            sensors=read(folder/'telemetry.csv') if (folder/'telemetry.csv').exists() else []
            if sensors:
                temperatures=[float(s['thermal_zone0_temp_mc'])/1000 for s in sensors]
                row.update(mean_soc_temp_c=statistics.mean(temperatures),max_soc_temp_c=max(temperatures))
            if m['status']=='FINISHED':
                try:
                    analysis_folder=report/'analysis'/item['folder']
                    shutil.copytree(folder,analysis_folder,dirs_exist_ok=True)
                    row.update(analyze_run(analysis_folder,item['expected_frames'])); row['finished_input']=True
                    row['valid']=not(row['cpu_drop'] or row['dmc_drop'] or row['thermal_cap']) and row['cpu_restored'] and row['dmc_restored']
                    row['status']='完成' if row['valid'] else '未完成'; row['reason']='' if row['valid'] else '环境条件未通过'
                except Exception as e: row['reason']=str(e)
            else: row['reason']=m.get('error') or 'SLAM process exited with code '+str(m.get('exit_code'))
            print('%s %s #%d | 跑完=%s | ATE=不适用（无真值） | 降频=%s'%(item['clip'],item['configuration'],item['run_index'],row['finished_input'],row['cpu_drop'] or row['dmc_drop'] or row['thermal_cap']))
        results.append(row)
    fields=list(dict.fromkeys(k for row in results for k in row)); write(report/'results_c2.csv',results,fields)
    summaries=[]
    metrics=['state_ok_fraction','first_initialization_frame','first_initialization_time_s','loss_segments','maps','keyframes','map_points',
        'total_mean_ms','total_median_ms','total_p95_ms','orb_median_ms','orb_p95_ms','orb_ratio_frame_median','orb_ratio_sums',
        'inliers_mean','inliers_median','inliers_p95','total_gt33_fraction','total_gt50_fraction','mean_soc_temp_c']
    for clip,configuration in sorted({(r['clip'],r['configuration']) for r in results}):
        group=[r for r in results if r['clip']==clip and r['configuration']==configuration and r['valid']]
        for metric in metrics:
            values=[float(r[metric]) for r in group if r.get(metric,'')!='']
            summaries.append(dict(clip=clip,configuration=configuration,valid_runs=len(group),metric=metric,
                median=statistics.median(values) if values else '',min=min(values) if values else '',max=max(values) if values else ''))
    write(report/'summary.csv',summaries,list(summaries[0]))
    pairs=[]
    groups={ (i['clip'],i['configuration']) for i in state['schedule'] }
    for group in sorted(groups):
        items=[i for i in state['schedule'] if (i['clip'],i['configuration'])==group and i.get('status')=='FINISHED']
        for aitem,bitem in itertools.combinations(items,2):
            row=dict(clip=group[0],comparison='within_'+group[1],reference=aitem['folder'],estimate=bitem['folder'],status='完成',reason='')
            try: row.update(compare(runtime/aitem['folder'],runtime/bitem['folder']))
            except Exception as e: row.update(status='未完成',reason=str(e))
            pairs.append(row)
    selected=state.get('sensitivity_clip')
    if selected:
        baseline=[i for i in state['schedule'] if i['clip']==selected and i['configuration']=='provisional' and i.get('status')=='FINISHED']
        variants=[i for i in state['schedule'] if i['configuration']!='provisional' and i.get('status')=='FINISHED']
        for aitem,bitem in itertools.product(baseline,variants):
            row=dict(clip=selected,comparison='provisional_vs_'+bitem['configuration'],reference=aitem['folder'],estimate=bitem['folder'],status='完成',reason='')
            try: row.update(compare(runtime/aitem['folder'],runtime/bitem['folder']))
            except Exception as e: row.update(status='未完成',reason=str(e))
            pairs.append(row)
    write(report/'trajectory_consistency.csv',pairs,list(dict.fromkeys(k for r in pairs for k in r)) or ['status'])
    shutil.copy2(runtime/'batch_state.json',report/'batch_state.json')
    lines=['# C2 初步结果','', '**临时内参，待标定后重跑；无真值，无ATE。**','',
        '状态：'+state['status']+'；逐次结果见 results_c2.csv，三次中位数/最小/最大见 summary.csv。',
        '每段重复轨迹及焦距敏感性比较见 trajectory_consistency.csv；仅比较最大最终地图的共同OK轨迹段，报告覆盖率。',
        '误差以参考轨迹任意SLAM长度单位及归一化RMS表示，不标为米或绝对精度。',
        '每个丢失片段的时间、帧范围、恢复地图及重定位标记在 raw/*/loss_segments.csv。',
        '首尾实际同位置尚未由用户确认，因此首尾闭合误差未完成。',
        '丢失图像与原因人工审阅待完成，B2未启动。']
    (report/'C2_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
if __name__=='__main__': main()
