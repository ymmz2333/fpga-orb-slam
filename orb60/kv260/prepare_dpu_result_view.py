"""Prepare a verified DPU component reconstruction for the existing GPU viewer."""
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
    run,output=Path(run),Path(output)
    component=json.loads((run/'COMPONENT.json').read_text())
    dense=json.loads((run/'dense/status.json').read_text())
    if component['status']!='ACTUAL_DPU_SAVED_POSE_RECONSTRUCTION_PASS' or dense['backend']!='kv260_dpu' or not dense['hardware_inference_verified']:
        raise ValueError('Completed real DPU component reconstruction required')
    if output.exists():raise ValueError('Fresh viewer directory required')
    entry=dense['maps'][0];mid=entry['map_id'];xyz,rgb=read_ply(run/f'dense/map_{mid}_dense.ply')
    if len(xyz)!=entry['points'] or not len(xyz) or not np.isfinite(xyz).all():raise ValueError('Invalid colored cloud')
    output.mkdir(parents=True)
    shutil.copy2(run/f'dense/map_{mid}_dense.ply',output/'dense.ply')
    def rows(name):
        with (run/'tracking/map'/name).open(newline='') as stream:return list(csv.DictReader(stream))
    points=rows('points.csv');keys=rows('keyframes.csv')
    sparse=np.array([[float(r[k]) for k in ('x','y','z')] for r in points],np.float32)
    write_ply(output/'sparse.ply',sparse,np.full((len(sparse),3),190,np.uint8))
    poses=[{'keyframe_id':int(row['keyframe_id']),'twc':[[float(row[f'twc_{r}{c}']) for c in range(4)] for r in range(4)]} for row in keys]
    save(output/'poses.json',poses)
    metas=[json.loads(p.read_text()) for p in (run/'dense/color_poses').glob('f*.json')]
    meta=max((m for m in metas if m['map_id']==mid),key=lambda m:m['source_frame_id'])
    image=FrameStore(run/'dense/rgb_cache').read(meta)
    if not cv2.imwrite(str(output/'preview_rgb.png'),image):raise ValueError('Cannot write paired RGB preview')
    save(output/'preview_features.json',np.asarray(meta['observations'])[:,:2].tolist())
    block=json.loads((run/'dense/blocks'/f'm{mid}_f{meta["source_frame_id"]}.final.json').read_text())
    result={'status':'ACTUAL_DPU_SAVED_POSE_RESULT_VIEW','backend':'kv260_dpu','points':len(xyz),'sparse_points':len(sparse),
            'cloud':'dense.ply','sparse':'sparse.ply','poses':'poses.json','preview_rgb':'preview_rgb.png',
            'preview_features':'preview_features.json','map_id':mid,'voxel_edge':block['voxel_edge'],
            'preview_source_frame':meta['source_frame_id'],'preview_keyframe':meta['keyframe_id'],
            'valid_depth_keyframes':dense['depth_frames'],'world_scale':1,'hardware_verified':True,
            'hardware_dpu_inference':True,'mapping_reexecuted':False,'pl_executed_in_view':False,
            'source':'Actual KV260 DPU depth and PS RGB fusion using saved native PS poses and paired physical7015 input',
            'coordinate_system':'Original relative SLAM world; no display alignment','source_run':run.name}
    save(output/'result.json',result)
    print(json.dumps({'status':result['status'],'points':len(xyz)}))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    prepare(**vars(p.parse_args()))
