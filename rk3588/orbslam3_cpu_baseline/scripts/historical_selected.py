"""G1 archived selected counts; reconstruct missing native layer counts explicitly."""
import argparse,collections,csv,json,pathlib,statistics,struct,subprocess,time
from golden_audit_support import read_rows,atomic_json
ROOT=pathlib.Path(__file__).resolve().parents[1];PROJECT=ROOT.parents[1]
GOLDEN=PROJECT/'orb_frontend_golden';OLD=GOLDEN/'decision/G1_layers_resume_20261006_013559'

def write(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=pathlib.Path);a=p.parse_args();out=a.output;out.mkdir(exist_ok=False)
    datasets=json.loads((OLD/'configs/manifest.json').read_text())['datasets'][1:];all_frames=[];summaries=[];checks=0
    for d in datasets:
        folder=out/d['name'];folder.mkdir();prepared=pathlib.Path(d['input_hashes']).parent
        env=dict(__import__('os').environ,LD_LIBRARY_PATH=str(PROJECT/'.work/golden/opencv-install/lib'))
        for name,cmd in [('native',[str(PROJECT/'.work/golden_h2/native_counts/native_selected_counts'),str(prepared),d['timestamps'],str(folder/'native.csv')]),
            ('golden',[str(PROJECT/'.work/golden_h2/build/orb_golden_cli'),'--input',str(prepared),'--sequence',d['timestamps'],'--output',str(folder/'counts_only'),'--profiles','L8,L4,V0','--counts-only','1','--stats',str(folder/'golden.csv')])]:
            with (folder/(name+'.log')).open('w') as log:subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        grouped=collections.defaultdict(list)
        for r in read_rows(folder/'native.csv'):grouped['native',int(r['timestamp_ns']),int(r['role'])].append(r)
        for r in read_rows(folder/'golden.csv'):grouped[r['variant'],int(r['timestamp_ns']),int(r['role'])].append(r)
        # Every archived packet octave count must agree with counts-only generation,
        # before using reconstructed pre-truncation grid statistics.
        for (v,ns,role),layers in grouped.items():
            if v=='native':continue
            path=pathlib.Path(d['corpus'])/v/('initialization' if role else 'normal')/(str(ns)+'.orb');data=path.read_bytes()
            count=struct.unpack_from('<I',data,32)[0];counts=collections.Counter(struct.unpack_from('<i',data,64+i*64+8)[0] for i in range(count))
            if any(counts[int(r['level'])]!=int(r['selected']) for r in layers):raise ValueError('Archived octave mismatch '+str(path))
            checks+=1
        for v in ['native','V0','L8','L4']:
            for run_index in range(1,6):
                raw=OLD/'runs'/(d['name']+'__'+v+'__run%02d'%run_index)
                features=read_rows(raw/'FeatureTimeStats.csv');states=read_rows(raw/'TrackingStates.csv');meta=json.loads((raw/'run_metadata.json').read_text())
                for f,s in zip(features,states):
                    ns=int(f['timestamp_ns']);role=int(f['role']);layers=grouped[v,ns,role];total=sum(int(r['selected']) for r in layers)
                    if total!=int(f['count']):raise ValueError('Historical in-memory total differs '+str(raw)+' '+str(ns))
                    level0=next(r for r in layers if r['level']=='0');budget=sum(int(r['budget']) for r in layers)
                    cells=sum(int(r.get('cell_cols',0))*int(r.get('cell_rows',0)) for r in layers)
                    empty=sum(int(r.get('empty_cells',0)) for r in layers)
                    all_frames.append(dict(dataset=d['name'],variant=v,run_index=run_index,timestamp_ns=ns,role=role,state_after=s['state_after'],
                        run_status=meta['status'],scope='completed frames only' if meta['status']!='FINISHED' else 'full sequence',
                        level0_selected=int(level0['selected']),level0_budget=int(level0['budget']),all_selected=total,all_budget=budget,
                        shortfall=max(0,budget-total),grid_empty_fraction=empty/cells if cells else '',
                        empty_scope='G1 actual pre-global-truncation grid' if cells else 'not applicable: octree selection',
                        layer_count_source='native reconstruction; every historical used total verified' if v=='native' else 'archived packet octaves verified against counts-only model'))
        atomic_json(folder/'acceptance.json',dict(status='PASSED',archived_packet_octaves_checked=checks,native_missing_historical_octaves='reconstructed, not historical measured per-layer logs'))
    write(out/'selected_per_frame.csv',all_frames)
    for key in sorted({(r['dataset'],r['variant'],r['role']) for r in all_frames}):
        values=[r for r in all_frames if (r['dataset'],r['variant'],r['role'])==key];summary=dict(dataset=key[0],variant=key[1],role=key[2],frames=len(values),scope='all retained completed frames; failed L8 includes partial only')
        for field in ['level0_selected','level0_budget','all_selected','all_budget','shortfall','grid_empty_fraction']:
            vals=[r[field] for r in values if r[field]!=''];summary[field+'_median']=statistics.median(vals) if vals else '';summary[field+'_min']=min(vals) if vals else '';summary[field+'_max']=max(vals) if vals else ''
        summary['empty_scope']=values[0]['empty_scope'];summaries.append(summary)
    write(out/'selected_summary.csv',summaries)
    (out/'README.md').write_text('G1既有数据。native历史只记录总数；逐层数由原提取器在相同原始图像重建，并逐帧核对全部历史使用总数，不能称历史逐层实测。V0/L8/L4逐层数来自归档包。L8/L4空格为原G1重新计算、截断前统计，并逐帧/两角色核对包内各层数量；native/V0四叉树没有实际格子，空格比例不适用。失败L8只覆盖卡死前已完成帧，不能与全程比例混淆。\n',encoding='utf-8')
    atomic_json(out/'acceptance.json',dict(status='PASSED',archive_packet_checks=checks,historical_used_frames_checked=len(all_frames)))
    print('HISTORICAL_SELECTED_PASS frames='+str(len(all_frames)))
if __name__=='__main__':main()
