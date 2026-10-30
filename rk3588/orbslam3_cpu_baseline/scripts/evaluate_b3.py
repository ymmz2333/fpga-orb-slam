"""PC-only reproducible B3 CSV/Sim3 summaries, using fresh five-run native controls."""
import argparse,csv,itertools,json,math,pathlib,shutil,statistics
from analyze_b2 import analyze
from analyze_c import read
from evaluate_a2 import evaluate
from finish_c import compare

def write(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--output',required=True)
    p.add_argument('--euroc',required=True);a=p.parse_args();raw=pathlib.Path(a.raw);out=pathlib.Path(a.output)
    state=json.loads((raw/'batch_state.json').read_text(encoding='utf-8'))
    if state['status']=='RUNNING':raise SystemExit('Batch is running; do not poll or analyze partial results')
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((raw/'configs/manifest.json').read_text(encoding='utf-8'));datasets={d['name']:d for d in manifest['datasets']}
    records=[]
    for item in state['schedule']:
        d=dict(datasets[item['dataset']]);d['path']=str(pathlib.Path(a.euroc)) if d['kind']=='euroc' else d['path']
        source=raw/'runs'/item['folder'];row=dict(dataset=d['name'],variant=item['variant'],run_index=item['run_index'],
            folder=item['folder'],status='未完成',error=item.get('error','未执行'),intrinsics_label=d['intrinsics_label'],ate_rmse_m='未完成')
        meta_path=source/'run_metadata.json'
        if meta_path.exists():
            meta=json.loads(meta_path.read_text(encoding='utf-8'));row.update(cpu_drop=meta['frequency_drop_detected'],dmc_drop=meta['dmc_frequency_drop'])
            if meta['status']=='FINISHED':
                try:
                    folder=out/'analysis'/item['folder'];shutil.copytree(source,folder)
                    row.update(analyze(folder,d,item['variant'],d['full_frames']),status='完成',error='')
                    if not row['initialization_succeeded']:row.update(status='初始化失败',error='全段未出现 OK')
                    if d['kind']=='euroc' and row['initialization_succeeded']:
                        ate=evaluate(folder,pathlib.Path(a.euroc));row.update(ate_rmse_m=ate['ate_rmse_m'],ate_evaluation_method=ate['evaluation_method'],ate_associated_poses=ate['associated_poses'])
                    if meta['frequency_drop_detected'] or meta['dmc_frequency_drop']:row.update(status='降频影响',error='频率不满足条件')
                except Exception as e:row.update(status='未完成',error=str(e))
        records.append(row)
    write(out/'results_exp3.csv',records)
    pairs=[]
    for d in manifest['datasets']:
        if d['kind']!='prepared':continue
        groups={v:[r for r in records if r['dataset']==d['name'] and r['variant']==v and r['status']=='完成'] for v in manifest['plan']['variants']}
        for v,g in groups.items():
            comparisons=[(left,right,'within_'+v) for left,right in itertools.combinations(g,2)]
            if v!='native':comparisons += [(left,right,'native_vs_'+v) for left in groups['native'] for right in g]
            for left,right,kind in comparisons:
                row=dict(dataset=d['name'],variant=v,comparison=kind,left=left['folder'],right=right['folder'],status='未完成')
                try:row.update(compare(out/'analysis'/left['folder'],out/'analysis'/right['folder']),status='完成')
                except Exception as e:row['reason']=str(e)
                pairs.append(row)
    if pairs:write(out/'trajectory_consistency.csv',pairs)
    summary=[]
    for d in manifest['datasets']:
        native_range=[r['normalized_rms'] for r in pairs if r['dataset']==d['name'] and r['comparison']=='within_native' and r['status']=='完成']
        native_coverage=[r['input_coverage'] for r in pairs if r['dataset']==d['name'] and r['comparison']=='within_native' and r['status']=='完成']
        for variant in manifest['plan']['variants']:
            g=[r for r in records if r['dataset']==d['name'] and r['variant']==variant]
            valid=[r for r in g if r['status']=='完成'];row=dict(dataset=d['name'],variant=variant,attempts=len(g),valid_runs=len(valid),intrinsics_label=d['intrinsics_label'])
            for key in ('ate_rmse_m','state_ok_fraction','first_initialization_frame','loss_segments','maps','inliers_median','total_median_ms','total_p95_ms','remaining_ms_median','read_ms_median','points_median','orb_ratio_frame_median','orb_ratio_sums'):
                values=[float(r[key]) for r in valid if isinstance(r.get(key),(float,int)) and math.isfinite(float(r[key]))]
                for name,func in (('median',statistics.median),('min',min),('max',max)):
                    row[key+'_'+name]=func(values) if values else '未完成'
            differences=[r['normalized_rms'] for r in pairs if r['dataset']==d['name'] and r['comparison']=='native_vs_'+variant and r['status']=='完成']
            if d['kind']=='prepared' and variant!='native':
                coverage=[r['input_coverage'] for r in pairs if r['dataset']==d['name'] and r['comparison']=='native_vs_'+variant and r['status']=='完成']
                enough=bool(coverage and native_coverage and min(coverage)>=min(native_coverage))
                row['relative_shape_judgement']=('无可测差异' if max(differences)<=max(native_range) else '超出 native 重复性范围') if differences and native_range and enough and len(valid)==5 and len([r for r in records if r['dataset']==d['name'] and r['variant']=='native' and r['status']=='完成'])==5 else '未完成／公共覆盖不足'
                row['native_repeatability_max']=max(native_range) if native_range else '未完成'
            summary.append(row)
    write(out/'summary_exp3.csv',summary)
    print('B3_PC_EVALUATED attempts=%d; no absolute Tello accuracy asserted'%len(records))
if __name__=='__main__':main()
