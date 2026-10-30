"""Rebase NPU group-local clouds into final raw SLAM coordinates for Map V2."""
import csv,json
from pathlib import Path
import numpy as np
from orb60.dense.geometry import camera_points,fit_inverse_depth,VoxelMap,valid_pose
from .dense_environment import POINT,write,validate

def rows(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))

def pose(row):return np.array([[float(row['twc_%d%d'%(r,c)]) for c in range(4)] for r in range(4)])

def build(run,folder,camera):
    run,folder,camera=map(Path,(run,folder,camera));mid=int((run/'tracking/map/map_id.txt').read_text())
    final={int(r['slam_timestamp_ns']):pose(r) for r in rows(run/'tracking/map/final_frames.csv') if int(r['map_id'])==mid}
    by_frame={int(r['source_frame_id']):r for r in rows(run/'tracking/frames.csv')}
    landmarks={int(r['point_id']):[float(r[k]) for k in ('x','y','z')] for r in rows(folder/'points.csv')}
    voxel=None;accepted=[];skipped=[]
    for file in sorted((run/'dense/chunks').glob('*.json')):
        try:
            meta=json.loads(file.read_text());anchor=json.loads((run/'dense/anchors'/file.name).read_text())
            frame=int(meta['source_frame_index']);journal=by_frame[frame];twc=final[int(journal['slam_timestamp_ns'])]
            if not valid_pose(twc):raise ValueError('invalid final anchor pose')
            obs=np.asarray(anchor['observations'],float)
            if obs.ndim!=2 or obs.shape[1]!=6:raise ValueError('anchor requires landmark IDs')
            ids=[i for i,o in enumerate(obs) if int(o[5]) in landmarks]
            if len(ids)<20:raise ValueError('fewer than 20 retained anchor landmarks')
            oldz=camera_points(obs[ids,2:5],np.asarray(anchor['twc']))[:,2]
            xyz=np.array([landmarks[int(obs[i,5])] for i in ids]);newz=camera_points(xyz,twc)[:,2]
            good=np.isfinite(oldz)&np.isfinite(newz)&(oldz>1e-6)&(newz>1e-6)
            a,b,quality=fit_inverse_depth(1/oldz[good],newz[good],seed=frame)
            raw=file.with_suffix('.bin').read_bytes()
            if len(raw)!=int(meta['points'])*POINT.itemsize:raise ValueError('chunk byte count mismatch')
            chunk=np.frombuffer(raw,POINT);local=chunk['xyz'].astype(float);old=local[:,2]
            with np.errstate(divide='ignore',invalid='ignore'):new=1/(a/old+b)
            limits=np.percentile(newz[good],[5,95])
            good_point=np.isfinite(local).all(axis=1)&np.isfinite(new)&(old>1e-6)&(new>limits[0]*.25)&(new<limits[1]*4)
            local=local[good_point];new=new[good_point]
            if len(local)<100:raise ValueError('insufficient final valid dense points')
            local*=new[:,None]/local[:,2:3]
            world=local@twc[:3,:3].T+twc[:3,3]
            if voxel is None:voxel=VoxelMap(float(np.median(newz[good]))*.004,capacity=2000000)
            voxel.add(world,chunk['rgb'][good_point])
            accepted.append(dict(chunk=file.name,source_frame_id=frame,points=len(local),inverse_depth_update=dict(slope=a,intercept=b,**quality)))
        except (ValueError,KeyError,OSError) as exc:skipped.append(dict(chunk=file.name,reason=str(exc)))
    if voxel is None:raise ValueError('No dense groups with final optimized poses and >=20 common landmarks; old map preserved')
    xyz,rgb=voxel.arrays()
    if len(xyz)<1000:raise ValueError('Fewer than 1000 final dense environment points; old map preserved')
    path=folder/'dense_environment.bin';write(path,xyz,rgb,folder/'points.csv',camera);validate(path,folder/'points.csv',camera)
    report=dict(points=len(xyz),map_id=mid,accepted=accepted,skipped=skipped,voxel_edge=voxel.edge,
                coordinates='final optimized raw SLAM world; no origin reset or trajectory fitting',
                source='actual RK NPU; group local points reanchored via final frame poses and shared landmark depth')
    (run/'dense/dense_handover.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
