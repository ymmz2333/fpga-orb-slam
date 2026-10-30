"""User-triggered B2 collection. Refuse active batch; preserve raw bytes and hashes."""
import argparse,csv,hashlib,json,pathlib,re,shutil,statistics,subprocess,tarfile
from analyze_c import read
from analyze_a2 import describe
ROOT=pathlib.Path(__file__).resolve().parent.parent

def write(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);p.add_argument('--download',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.batch):raise ValueError('Invalid batch ID')
    runtime=ROOT/'runtime/b2'/a.batch;runtime.mkdir(parents=True,exist_ok=True)
    if a.download:
        board=json.loads((ROOT/'local_board.json').read_text(encoding='utf-8'));prefix=board.get('sshAlias','rk3588')+':'+board['remoteRoot']+'/runtime/b2/'+a.batch+'/'
        subprocess.run(['scp','-q',prefix+'batch_state.json',str(runtime/'batch_state.json')],check=True)
        state=json.loads((runtime/'batch_state.json').read_text(encoding='utf-8'))
        if state['status']=='RUNNING':raise SystemExit('Still running; no log polling or result download')
        if state['status']!='FINISHED':raise SystemExit('Batch paused/failed: '+state.get('reason',state['status']))
        subprocess.run(['scp','-q',prefix+'results.tar.gz',str(runtime/'results.tar.gz')],check=True)
        if hashlib.sha256((runtime/'results.tar.gz').read_bytes()).hexdigest()!=state['export_sha256']:raise ValueError('Result archive SHA256 mismatch')
        with tarfile.open(runtime/'results.tar.gz') as archive:archive.extractall(runtime,filter='data')
    state=json.loads((runtime/'batch_state.json').read_text(encoding='utf-8'))
    if state['status']!='FINISHED':raise SystemExit('B2 is not finished')
    for row in read(runtime/'raw_manifest.csv'):
        path=runtime/row['path']
        if not path.is_file() or path.stat().st_size!=int(row['bytes']) or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Raw transport mismatch '+row['path'])
    report=ROOT/'reports/b2'/a.batch;report.mkdir(parents=True,exist_ok=False)
    shutil.copytree(runtime,report/'raw',ignore=shutil.ignore_patterns('results.tar.gz'))
    manifest=json.loads((runtime/'configs/manifest.json').read_text(encoding='utf-8'))
    dataset_lookup={d['name']:d for d in manifest['datasets']}
    rows=[];units=[];thresholds=[]
    for item in state['schedule']:
        row=dict(dataset=item['dataset'],variant=item['variant'],status=item.get('status','未完成'),acceptance=item.get('acceptance','未完成'),
            processed_frames='未完成',cpu_drop=item.get('cpu_drop','未完成'),dmc_drop=item.get('dmc_drop','未完成'),generation_wall_s=item.get('generation_wall_s',''),
            folder=item['folder'],recovery_of=item.get('recovery_of',''),error=item.get('error',''),intrinsics_label=dataset_lookup[item['dataset']]['intrinsics_label'])
        row.update(item.get('facts',{}));rows.append(row)
        check=runtime/'candidate_checks'/item['folder']
        if check.exists():
            desc=read(check/'descriptor_audit.csv');layers=read(check/'layers.csv')
            unit=dict(dataset=item['dataset'],variant=item['variant'],packet_check=item['packet_check']['status'],
                files=item['packet_check']['files'],audited_descriptors=len(desc),
                native_byte_equal=all(r['native_byte_equal']=='1' for r in desc) if item['variant']=='V0' else '',
                layer_rows=len(layers),shortfall_total=sum(int(r['shortfall']) for r in layers))
            unit.update({'hamming_'+k:v for k,v in describe([int(r['hamming_same_keypoint']) for r in desc]).items()});units.append(unit)
    write(report/'results_b2_smoke.csv',rows);write(report/'candidate_unit_summary.csv',units)
    for directory in sorted((runtime/'fast_probe').iterdir()):
        probe=read(directory/'fast_probe.csv')
        for role in (0,1):
            for threshold in sorted({int(r['threshold']) for r in probe}):
                group=[r for r in probe if int(r['role'])==role and int(r['threshold'])==threshold]
                result=dict(dataset=directory.name,role='initialization' if role else 'normal',threshold=threshold,frames=len(group))
                for key in ('candidates','selected','shortfall'):
                    result.update({key+'_'+k:v for k,v in describe([int(r[key]) for r in group]).items()})
                result.update({'empty_fraction_'+k:v for k,v in describe([int(r['empty_cells'])/(int(r['cell_cols'])*int(r['cell_rows'])) for r in group]).items()});thresholds.append(result)
    write(report/'fast_threshold_summary.csv',thresholds)
    # Forecast only, using observed generation wall time and input duration; no FPGA extraction performance claim.
    generation=0;corpus_bytes=0
    for d in manifest['datasets']:
        for variant in manifest['plan']['variants']:
            complete=[i for i in state['schedule'] if i['dataset']==d['name'] and i['variant']==variant and i.get('packet_check',{}).get('status')=='PASS']
            timed=[i for i in complete if 'generation_wall_s' in i]
            if timed:generation+=float(timed[-1]['generation_wall_s'])*d['full_frames']/d['smoke_frames']
            if complete:corpus_bytes+=complete[-1].get('corpus_packet_bytes',0)*d['full_frames']/d['smoke_frames']
    # Historical native wall times only forecast queue duration; B3 measurements will be fresh.
    slam_seconds=0;reference_sources=[]
    for d in manifest['datasets']:
        files=list(ROOT.glob(d.get('forecast_reference','no-match')))
        values=[]
        for path in files:
            metadata=json.loads(path.read_text(encoding='utf-8'))
            if metadata.get('status')=='FINISHED' and metadata.get('wall_time_s'):
                values.append(float(metadata['wall_time_s']));reference_sources.append(path.relative_to(ROOT).as_posix())
        if values:wall=statistics.median(values)
        else:
            native=next(i for i in state['schedule'] if i['dataset']==d['name'] and i['variant']=='native')
            wall=float(native['wall_time_s'])*d['full_frames']/d['smoke_frames']
            reference_sources.append('B2 smoke native wall-time linear extrapolation: '+d['name'])
        slam_seconds+=5*len(manifest['plan']['variants'])*wall
    forecast=dict(kind='预计时长，不是实验性能结果',formal_round_one_runs=150,forced_loss_runs=0,
        slam_forecast_s=slam_seconds,feature_generation_linear_forecast_s=generation,
        total_forecast_h=(slam_seconds+generation)/3600,full_corpus_packet_bytes_forecast=corpus_bytes,
        assumptions='同实时节奏；600帧生成时间/文件容量线性外推；另加校验、冷却与存储余量',
        historical_wall_time_sources=reference_sources)
    (report/'b3_duration_forecast.json').write_text(json.dumps(forecast,indent=2,ensure_ascii=False),encoding='utf-8')
    for row in rows:
        drop=(row['cpu_drop'] is True or row['dmc_drop'] is True) if isinstance(row['cpu_drop'],bool) and isinstance(row['dmc_drop'],bool) else '未记录'
        print('%s | %s%s | 跑完=%s | 初始化=%s | 降频=%s'%(row['dataset'],row['variant'],'（输入恢复验证）' if row['recovery_of'] else '',row.get('processed_frames')==manifest['plan']['smoke_frames'],row.get('initialization_succeeded','未完成'),drop))
    print('B2_COLLECTED '+str(report));print('B3_FORECAST_H %.2f (not started)'%forecast['total_forecast_h'])
if __name__=='__main__':main()
