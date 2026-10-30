"""Portable offline replay from the SAME final SLAM run, without invented poses."""
import collections
import csv
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np


def quaternion_pose(row):
    x,y,z,w=row[4:8];norm=np.linalg.norm([x,y,z,w])
    if not np.isfinite(row).all() or abs(norm-1)>.01:
        raise ValueError('Invalid recorded trajectory quaternion')
    x,y,z,w=np.array([x,y,z,w])/norm
    pose=np.eye(4)
    pose[:3,:3]=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                  [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                  [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
    pose[:3,3]=row[1:4]
    return pose


def prepare_replay(source,folder,map_id,source_frames):
    source,folder=Path(source),Path(folder)
    report=json.loads((source/('map_%d'%map_id)/'result.json').read_text())
    manifest=json.loads((source/'keyframes.json').read_text())
    info=next(m for m in manifest['maps'] if m['map_id']==map_id)
    scale=report['world_scale']
    # Diagnostics_mapN is exported for this particular map, never concatenate maps.
    path=source/'slam'/('Diagnostics_map%d.txt'%map_id)
    if not path.is_file() and map_id==0:path=source/'slam/CameraTrajectory.txt'
    rows=np.loadtxt(path,ndmin=2)
    poses={int(round(r[0])):quaternion_pose(r) for r in rows}
    shared=0;error=0.
    for frame in info['frames']:
        stamp=frame['timestamp_ns'];pose=np.array(frame['twc'])
        if stamp in poses:
            shared+=1;error=max(error,float(np.max(np.abs(poses[stamp]-pose))))
        poses[stamp]=pose
    if shared<2 or error>1e-4:
        raise ValueError('Per-frame trajectory does not match final dense-map keyframes')
    obs=collections.defaultdict(list)
    with (source/'slam/keyframes'/('map_%d'%map_id)/'observations.csv').open() as f:
        for r in csv.DictReader(f):obs[int(r['keyframe_id'])].append([float(r['u']),float(r['v'])])
    keys={f['timestamp_ns']:f for f in info['frames']}
    frames=[]
    with Path(source_frames).open() as f:
        for r in csv.DictReader(f):
            stamp=int(r['timestamp_ns']);pose=poses.get(stamp)
            if pose is not None:
                pose=pose.copy();pose[:3,3]*=scale
            entry=dict(source_frame_index=int(r['source_frame_index']),timestamp_ns=stamp,
                       pts_s=float(r['mp4_pts_s']),twc=pose.tolist() if pose is not None else None)
            if stamp in keys:
                key=keys[stamp];image=source/key['rgb'];relative='keyframes/'+image.name
                target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True)
                if image.resolve()!=target.resolve():shutil.copy2(image,target)
                entry.update(keyframe_id=key['keyframe_id'],rgb=relative,uv=obs[key['keyframe_id']])
            frames.append(entry)
    if not frames or any(a['pts_s']>=b['pts_s'] for a,b in zip(frames,frames[1:])):
        raise ValueError('Replay source PTS must be strictly increasing')
    calibration=info['frames'][0]
    replay=dict(format_version=1,frames=frames,k=calibration['k'],distortion=calibration['distortion'],
                image_shape=[720,960],video_sha256=json.loads((source/'result.json').read_text())['video_sha256'],
                pose_source='same-run final map diagnostics, verified against final keyframes',
                checked_keyframe_poses=shared,max_pose_error=error,
                feature_semantics='Actual reliable FPGA/SLAM observations on keyframes only; no features fabricated on other frames')
    status=source/'slam/status.json'
    if status.is_file():replay['tracking_fps']=json.loads(status.read_text()).get('processing_fps')
    prep=source/'dataset/preparation.json'
    if manifest.get('preparation'):replay['preparation']=manifest['preparation']
    elif prep.is_file():replay['preparation']=json.loads(prep.read_text())
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'replay.json').write_text(json.dumps(replay,separators=(',',':'))+'\n')
    return dict(frames=len(frames),keyframes=len(keys),checked_keyframe_poses=shared,max_pose_error=error)
