"""Dataset-independent no-ground-truth tracking diagnostics and timing summary."""
import argparse,csv,json,pathlib,statistics
from analyze_a2 import analyze,describe
def read(path):
    with pathlib.Path(path).open(encoding='utf-8',newline='') as f: return list(csv.DictReader(f))
def write(path,rows,fields):
    with pathlib.Path(path).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def check_timestamp(timestamp_ns,timestamp_s):
    # mono_euroc::LoadImages reads nanoseconds as double, then multiplies by
    # 1e-9. Division gives a different rounded double for some epoch stamps.
    # Compare the exact represented value using the reader's conversion;
    # no widened tolerance and no changes to the original timestamp logs.
    if float(int(timestamp_ns))*1e-9 != float(timestamp_s):
        raise ValueError('Timestamp association mismatch')
def analyze_run(folder,expected_frames=None,expected_extractor_calls=1):
    folder=pathlib.Path(folder); timing=analyze(folder,expected_frames)
    frames=read(folder/'frames.csv'); features=read(folder/'FeatureTimeStats.csv'); maps=read(folder/'MapStateStats.csv')
    if len(features)!=len(frames) or len(maps)!=len(frames): raise ValueError('Diagnostic row alignment mismatch')
    for i,(f,m,k) in enumerate(zip(frames,maps,features)):
        if int(m['frame_index'])!=i or int(k['frame_index'])!=i or int(k['extractor_calls'])!=expected_extractor_calls: raise ValueError('Diagnostic extractor-call invariant failed')
        check_timestamp(k['timestamp_ns'],f['timestamp_s'])
    first=next((i for i,f in enumerate(frames) if int(f['state_after'])==2),None)
    losses=[]; i=first+1 if first is not None else len(frames)
    while i<len(frames):
        if int(frames[i]['state_after'])==2: i+=1; continue
        start=i
        while i<len(frames) and int(frames[i]['state_after'])!=2: i+=1
        recovered=i<len(frames); end_time=float(frames[i]['timestamp_s']) if recovered else float(frames[-1]['timestamp_s'])
        losses.append(dict(segment=len(losses)+1,start_frame=start,end_frame=i-1,
            start_s=float(frames[start]['timestamp_s'])-float(frames[0]['timestamp_s']),
            end_s=end_time-float(frames[0]['timestamp_s']),duration_s=end_time-float(frames[start]['timestamp_s']),
            frames=i-start,recovered=recovered,map_before=maps[start-1]['map_id'],
            map_after=maps[i]['map_id'] if recovered else '',same_map=recovered and maps[start-1]['map_id']==maps[i]['map_id'],
            actual_relocalization=any(int(m['relocalized']) for m in maps[start:i+1]),
            includes_reinitialization=any(int(f['state_after']) in (0,1) for f in frames[start:i])))
    write(folder/'loss_segments.csv',losses,['segment','start_frame','end_frame','start_s','end_s','duration_s','frames','recovered','map_before','map_after','same_map','actual_relocalization','includes_reinitialization'])
    normal=[i for i,f in enumerate(frames) if f['category']=='normal']
    inliers=[int(features[i]['inliers']) for i in normal if int(features[i]['inliers'])>=0]
    map_rows=read(folder/'Diagnostics_maps.csv')
    if len(map_rows)!=timing['maps']: raise ValueError('Final map counts differ from SessionInfo')
    result=dict(timing,first_initialization_frame=(first+1 if first is not None else ''),
        first_initialization_time_s=float(frames[first]['timestamp_s'])-float(frames[0]['timestamp_s']) if first is not None else '',
        state_ok_frames=sum(int(f['state_after'])==2 for f in frames),
        state_ok_fraction=sum(int(f['state_after'])==2 for f in frames)/len(frames),
        loss_segments=len(losses),relocalized_frames=sum(int(m['relocalized']) for m in maps),
        same_map_recoveries=sum(l['same_map'] for l in losses),
        keyframes=sum(int(m['keyframes']) for m in map_rows),map_points=sum(int(m['map_points']) for m in map_rows),
        initialization_succeeded=first is not None,last_state=int(frames[-1]['state_after']),
        intrinsics_label='临时内参，待标定后重跑',ate_rmse_m='',ground_truth_available=False)
    result.update({'inliers_'+k:v for k,v in describe(inliers).items()})
    (folder/'c_facts.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('folder'); p.add_argument('--expected-frames',type=int); a=p.parse_args()
    f=analyze_run(a.folder,a.expected_frames)
    print('C_ANALYZED frames=%d OK=%.3f initialized=%s losses=%d'%(f['processed_frames'],f['state_ok_fraction'],f['initialization_succeeded'],f['loss_segments']))
