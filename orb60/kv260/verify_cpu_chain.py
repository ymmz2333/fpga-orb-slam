"""Verify a completed actual KV260 PL/PS CPU/GPU board run from raw results."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from .dense_fusion import save
from .frame_store import FrameStore
from orb60.dense.ply import read_ply
from orb60.dense.kv260.common import digest
from orb60.viewer.protocol import Snapshot


def verify(run,expected_frames):
    run=Path(run);system=json.loads((run/'system.json').read_text())
    if system.get('status')!='COMPLETED':raise ValueError('Full system has not exited successfully')
    if not system.get('live_kv260_pl') or system['orb_backend']!='PL' or system['depth_backend']!='ps_cpu':
        raise ValueError('Saved-feature or wrong depth backend is not this acceptance test')
    def rows(path):
        with path.open(newline='') as f:return list(csv.DictReader(f))
    frames=rows(run/'tracking/frames.csv');source=rows(run/'source_frames.csv')
    if len(frames)!=expected_frames or len(source)!=expected_frames:raise ValueError('Frame journal is incomplete')
    if [int(row['source_frame_id']) for row in frames]!=list(range(expected_frames)):raise ValueError('Actual PL frame sequence is incomplete')
    stamps=[int(row['timestamp_ns']) for row in frames]
    if any(a>=b for a,b in zip(stamps,stamps[1:])):raise ValueError('Nonmonotonic integer source timestamps')
    if any(int(row['cpu_orb_calls']) for row in frames):raise ValueError('CPU ORB fallback is forbidden')
    if [(int(row['timestamp_ns']),int(row['source_frame_index'])) for row in source]!=list(zip(stamps,range(expected_frames))):
        raise ValueError('GUI mapping differs from the exact input frame identity')
    if not (run/'tracking/map/EXPORT_COMPLETE').is_file():raise ValueError('Final map export is incomplete')
    dense=json.loads((run/'dense/status.json').read_text());cpu=json.loads((run/'dense/ps_depth.json').read_text())
    if dense['status']!='COMPLETED' or dense['backend']!='kv260_ps_cpu' or dense['hardware_inference_verified']:
        raise ValueError('Expected explicit completed PS CPU depth, no DPU claim')
    if cpu['provider']!=['CPUExecutionProvider'] or cpu['hardware_dpu_inference']:raise ValueError('Unexpected depth execution provider')
    selected=[json.loads(path.read_text()) for path in (run/'dense/color_poses').glob('f*.json')]
    store=FrameStore(run/'dense/rgb_cache')
    for meta in selected:
        if meta.get('anchor_kind')!='slam_keyframe' or meta['keyframe_id']<0:raise ValueError('A sampled tracking frame was labeled a keyframe')
        row=frames[meta['source_frame_id']]
        if meta['timestamp_ns']!=int(row['timestamp_ns']) or meta['gray_crc']!=int(row['gray_crc']):raise ValueError('RGB/pose/PL identity differs')
        image=store.read(meta)
        if image.shape!=(720,960,3):raise ValueError('Selected RGB image dimensions differ')
    clouds=[]
    for item in dense['maps']:
        path=run/f'dense/map_{item["map_id"]}_dense.ply';xyz,rgb=read_ply(path)
        if len(xyz)!=item['points'] or len(xyz)==0 or not np.isfinite(xyz).all():raise ValueError('Invalid actual RGB cloud')
        if rgb.shape!=(len(xyz),3) or rgb.dtype!=np.uint8 or not np.std(rgb.astype(float))>0:raise ValueError('Missing measured RGB payload')
        clouds.append(dict(map_id=item['map_id'],points=len(xyz),sha256=digest(path),
                           non_gray_fraction=float(np.mean(np.ptp(rgb.astype(int),axis=1)>3))))
    gpu=json.loads((run/'gpu_display.json').read_text())
    for key in ('gpu','gpu_sparse'):
        data=gpu[key]
        if data.get('software') or 'Mali' not in data.get('renderer','') or data.get('uploads',0)<=0:raise ValueError('Actual Mali GPU evidence missing: '+key)
    # The final per-process metrics and CRC-checked captured packet are durable
    # acceptance artifacts. Legacy desktop_status.json is an ephemeral monitor
    # which an additional offline viewer can overwrite; never reconstruct it.
    captured=Snapshot.decode((run/'gpu_snapshot/frame.orbv').read_bytes())
    if gpu.get('source')!='live' or gpu.get('last_frame')!=expected_frames-1 or gpu.get('displayed',0)<=0:
        raise ValueError('GPU source frame/display acceptance failed')
    if captured.meta['frame_index']!=expected_frames-1 or captured.meta['timestamp_ns']!=stamps[-1]:
        raise ValueError('Captured GPU input is not the exact final source frame')
    timing=dense['timings'];metrics=dict(inference_seconds=[item['inference_seconds'] for item in timing],
                                       fusion_seconds=[item['fusion_seconds'] for item in timing])
    for name,values in list(metrics.items()):
        if not values or not np.isfinite(values).all() or min(values)<0:raise ValueError('Invalid stage timing')
        metrics[name+'_median']=float(np.median(values))
    files=[run/'system.json',run/'tracking/frames.csv',run/'source_frames.csv',run/'dense/status.json',
           run/'dense/ps_depth.json',run/'gpu_display.json',run/'gpu_snapshot/frame.orbv',run/'depth_config.json']
    result=dict(status='ACTUAL_KV260_PL_PS_CPU_MIDAS_RGB_MALI_PASS',frames=len(frames),
                valid_poses=sum(int(row['pose_valid']) for row in frames),cpu_orb_calls=0,
                orb_backend='actual_KV260_PL',depth_backend='KV260_PS_CPU',dpu_used=False,
                selected_slam_keyframes=len(selected),depth_frames=len(timing),clouds=clouds,
                metrics=metrics,depth_fusion_process_rss_peak_mib=cpu['rss_peak_mib'],gpu_renderer=gpu['gpu']['renderer'],
                separate_gpu_maps=True,scope='Bounded recorded SD video on one KV260; not live-camera FPS or metric accuracy acceptance',
                sha256={p.relative_to(run).as_posix():digest(p) for p in files})
    save(run/'CPU_CHAIN_VALIDATION.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--frames',type=int,required=True)
    a=p.parse_args();print(json.dumps(verify(a.run,a.frames),indent=2))
