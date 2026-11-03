"""View an actual completed PL/PS CPU reconstruction in its original SLAM world."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import cv2
import numpy as np
from .dense_fusion import save
from .frame_store import FrameStore
from orb60.dense.ply import read_ply,write_ply


def prepare(run,output):
    run=Path(run);output=Path(output)
    system=json.loads((run/'system.json').read_text());dense=json.loads((run/'dense/status.json').read_text())
    if not system.get('live_kv260_pl') or system.get('cpu_orb_calls')!=0 or dense['backend']!='kv260_ps_cpu' or dense['status']!='COMPLETED':
        raise ValueError('Actual PL and completed PS CPU reconstruction required')
    if output.exists():raise ValueError('Fresh result-view folder required')
    entry=dense['maps'][0];mid=int(entry['map_id'])
    xyz,rgb=read_ply(run/f'dense/map_{mid}_dense.ply')
    if not len(xyz) or len(xyz)!=entry['points'] or not np.isfinite(xyz).all():raise ValueError('Dense payload count/geometry mismatch')
    output.mkdir(parents=True)
    shutil.copy2(run/f'dense/map_{mid}_dense.ply',output/'dense.ply')
    def rows(name):
        with (run/'tracking/map'/name).open(newline='') as f:return list(csv.DictReader(f))
    points=rows('points.csv');keys=rows('keyframes.csv')
    sparse=np.array([[float(row[k]) for k in ('x','y','z')] for row in points],np.float32)
    write_ply(output/'sparse.ply',sparse,np.full((len(sparse),3),190,np.uint8))
    poses=[{'keyframe_id':int(row['keyframe_id']),'twc':[[float(row[f'twc_{r}{c}']) for c in range(4)] for r in range(4)]} for row in keys]
    save(output/'poses.json',poses)
    selected=[json.loads(path.read_text()) for path in (run/'dense/color_poses').glob('f*.json')]
    meta=max(selected,key=lambda item:item['source_frame_id'])
    observations=np.asarray(meta['observations'],float)
    save(output/'preview_features.json',observations[:,:2].tolist())
    image=FrameStore(run/'dense/rgb_cache').read(meta)
    if not cv2.imwrite(str(output/'preview_rgb.png'),image):raise ValueError('Cannot write actual RGB preview')
    result=dict(status='ACTUAL_PL_PS_CPU_RECONSTRUCTION_VIEW',backend='kv260_ps_cpu',points=len(xyz),sparse_points=len(sparse),
                cloud='dense.ply',sparse='sparse.ply',poses='poses.json',preview_rgb='preview_rgb.png',
                map_id=mid,valid_depth_keyframes=dense['depth_frames'],
                voxel_edge=float(json.loads((run/'dense/blocks'/f'm{mid}_f{meta["source_frame_id"]}.json').read_text())['voxel_edge']),
                preview_features='preview_features.json',preview_keyframe=meta['keyframe_id'],
                preview_source_frame=meta['source_frame_id'],world_scale=1,
                coordinate_system='Original SLAM relative world; no display or depth-scale re-alignment',
                source='Actual KV260 PL ORB, native PS mapping, PS CPU MiDaS and RGB fusion; recorded SD video input',
                hardware_verified=True,hardware_dpu_inference=False,source_run=run.name)
    save(output/'result.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.run,a.output)))
