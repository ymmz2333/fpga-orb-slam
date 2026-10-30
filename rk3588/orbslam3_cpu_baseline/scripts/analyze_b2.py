"""Dataset-independent B2/B3 state-aligned metrics. No simulated FPGA timing."""
import csv,json,pathlib,statistics
from analyze_c import analyze_run,read
from analyze_a2 import describe

def analyze(folder,dataset,variant,expected_frames):
    folder=pathlib.Path(folder);mode='native' if variant=='native' else 'inject'
    facts=analyze_run(folder,expected_frames,0 if mode=='inject' else 1)
    frames=read(folder/'frames.csv');features=read(folder/'FeatureTimeStats.csv')
    facts.update(variant=variant,mode=mode,dataset=dataset['name'],design_label='设计候选',
        intrinsics_label=dataset['intrinsics_label'],ground_truth_available=dataset['kind']=='euroc',
        tracking_width=dataset['width'],tracking_height=dataset['height'],ate_rmse_m='未完成' if dataset['kind']=='euroc' else '不适用（无真值）',
        orb_slot_semantics='file_read_decode' if mode=='inject' else 'native_ORB',
        simulated_extraction_timing_is_fpga=False)
    aligned=[]
    for frame,feature in zip(frames,features):
        total,slot=float(frame['total_ms']),float(frame['orb_ms'])
        native=float(feature['native_ms']);read_ms=float(feature['read_ms']);decode_ms=float(feature['decode_ms'])
        if mode=='inject' and native!=0:raise ValueError('Inject called native extraction')
        if read_ms+decode_ms>slot+0.002 or native>slot+0.002:raise ValueError('Nested feature timing exceeds slot')
        aligned.append(dict(frame_index=frame['frame_index'],timestamp_ns=feature['timestamp_ns'],category=frame['category'],
            total_ms=total,feature_slot_ms=slot,remaining_ms=total-slot,read_ms=read_ms if mode=='inject' else '',decode_ms=decode_ms if mode=='inject' else '',
            native_ms=native,points=int(feature['count']),inliers=int(feature['inliers'])))
    normal=[r for r in aligned if r['category']=='normal']
    for metric in ('remaining_ms','read_ms','decode_ms','points'):
        facts.update({metric+'_'+k:v for k,v in describe([r[metric] for r in normal if r[metric]!='']).items()})
    for category in ('normal','initialization','lost'):
        selected=[r for r in aligned if r['category']==category]
        for metric in ('total_ms','feature_slot_ms','remaining_ms','read_ms','decode_ms'):
            facts.update({category+'_'+metric+'_'+k:v for k,v in describe([r[metric] for r in selected if r[metric]!='']).items()})
    if mode=='inject':facts.update(orb_ratio_frame_median='',orb_ratio_sums='')
    truth=pathlib.Path(dataset['path'])/'mav0/state_groundtruth_estimate0/data.csv'
    if dataset['kind']=='euroc' and truth.exists():
        with truth.open() as f:stamps=[int(r[0]) for r in csv.reader(f) if r and not r[0].startswith('#')]
        end=max(stamps);begin=min(stamps)
        facts.update(gt_ok_frames=sum(begin<=int(k['timestamp_ns'])<=end and int(f['state_after'])==2 for f,k in zip(frames,features)),
            gt_input_frames=sum(begin<=int(k['timestamp_ns'])<=end for k in features),
            tail_lost_frames=sum(int(k['timestamp_ns'])>end and int(f['state_after'])!=2 for f,k in zip(frames,features)))
    with (folder/'b2_frames.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(aligned[0]));w.writeheader();w.writerows(aligned)
    (folder/'b2_facts.json').write_text(json.dumps(facts,indent=2,ensure_ascii=False),encoding='utf-8')
    return facts
