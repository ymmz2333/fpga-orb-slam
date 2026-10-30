"""Associate new byte-verified PL records with the frozen final SLAM map."""
import argparse
import collections
from decimal import Decimal
from pathlib import Path
import shutil
import cv2
import numpy as np
from common import Features,feature_points,rows,write_rows,save,sha,pose_from_row,pose_fields

def raw_pose(fields):
    value=np.asarray(list(map(float,fields[1:])))
    if len(value)!=7 or not np.isfinite(value).all():raise ValueError('Invalid raw trajectory')
    t=value[:3];q=value[3:]
    if np.linalg.norm(q)<1e-12:raise ValueError('Zero trajectory quaternion')
    q=q/np.linalg.norm(q);x,y,z,w=q
    rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    pose=np.eye(4);pose[:3,:3]=rotation;pose[:3,3]=t;return pose

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--golden',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if __import__('json').loads((a.golden/'capture_acceptance.json').read_text())['status']!='PASS':raise ValueError('Physical capture required')
    out=a.output;out.mkdir(parents=True,exist_ok=False)
    features=Features(a.golden);bytime={int(r['timestamp_ns']):int(r['frame_index']) for r in features.index}
    if len(bytime)!=len(features.index):raise ValueError('Duplicate input timestamp')
    keys=rows(a.source/'slam/keyframes/map_0/keyframes.csv');obs=rows(a.source/'slam/keyframes/map_0/observations.csv')
    if len(keys)!=130:raise ValueError('Wrong frozen map')
    cache={};keybyid={int(k['keyframe_id']):k for k in keys}
    for key in keys:
        index=bytime[int(key['timestamp_ns'])];data=features.frame(index);uv=feature_points(data);lookup={}
        for j,r in enumerate(data):
            identity=(int(r['level']),int(r['x']),int(r['y']))
            if identity in lookup:raise ValueError('Ambiguous same-layer PL coordinate')
            lookup[identity]=j
        cache[int(key['keyframe_id'])]=(index,data,uv,lookup)
    scales=np.array([np.float32(1.2)**i for i in range(8)],np.float32)
    # Use the exact repeated float32 progression of the native adapter.
    scales[0]=1
    for i in range(1,8):scales[i]=scales[i-1]*np.float32(1.2)
    descriptors=[];points={};groups=collections.defaultdict(list);joined=[];maximum=0.
    for row in obs:
        kid,pid=int(row['keyframe_id']),int(row['point_id']);level=int(row['octave'])
        index,data,uv,lookup=cache[kid]
        raw=np.array([float(row['raw_u']),float(row['raw_v'])]);xy=np.rint(raw/scales[level]).astype(int)
        identity=(level,int(xy[0]),int(xy[1]))
        if identity not in lookup:raise ValueError('No exact historical observation/PL association')
        position=lookup[identity];error=float(np.max(np.abs(uv[position]-raw)));maximum=max(maximum,error)
        if error>.002:raise ValueError('Observation pixel mismatch')
        xyz=np.array([float(row[c]) for c in ('x','y','z')])
        if pid in points and not np.array_equal(points[pid],xyz):raise ValueError('Point world coordinates changed')
        points[pid]=xyz;drow=len(descriptors);descriptors.append(data['descriptor'][position].copy());groups[pid].append(drow)
        joined.append(dict(row,frame_index=index,record_index=position,descriptor_row=drow))
    desc=np.asarray(descriptors,np.uint8);desc.tofile(out/'observation_descriptors.bin')
    ids=sorted(points);lut=np.array([int(i).bit_count() for i in range(256)],np.uint8)
    representatives=[];pointrows=[];representative_rows=[]
    for pid in ids:
        candidates=groups[pid];d=desc[candidates]
        distances=lut[np.bitwise_xor(d[:,None,:],d[None,:,:])].sum(axis=2)
        selected=candidates[int(np.argmin(np.median(distances,axis=1)))];representative_rows.append(selected)
        representatives.append(desc[selected]);pointrows.append(dict(point_id=pid,x=points[pid][0],y=points[pid][1],z=points[pid][2],
             representative_observation_row=selected,observations=len(candidates)))
    np.asarray([points[i] for i in ids],dtype='<f4').tofile(out/'points.bin')
    np.asarray(ids,dtype='<u8').tofile(out/'point_ids.bin')
    np.asarray(representatives,np.uint8).tofile(out/'representative_descriptors.bin')
    write_rows(out/'points.csv',pointrows);write_rows(out/'observations.csv',joined);write_rows(out/'keyframes.csv',keys)
    with (out/'sparse_raw.ply').open('w') as f:
        f.write('ply\nformat ascii 1.0\ncomment raw SLAM map_0, relative scale\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\nend_header\n'%len(ids))
        np.savetxt(f,np.array([points[i] for i in ids]),fmt='%.17g')
    first=keys[0];pose=pose_from_row(first)
    positive=[((np.array([float(r[c]) for c in ('x','y','z')])-pose[:3,3])@pose[:3,:3])[2]
              for r in obs if int(r['keyframe_id'])==int(first['keyframe_id'])]
    depth=float(np.median([z for z in positive if z>0]))
    calibration=dict(k=[[float(first['fx']),0,float(first['cx'])],[0,float(first['fy']),float(first['cy'])],[0,0,1]],
         distortion=[float(first['d'+str(i)]) for i in range(5)],width=960,height=720,
         status='borrowed provisional intrinsics, not calibrated')
    save(out/'map.json',dict(format_version=1,map_id=0,points=len(ids),keyframes=len(keys),observations=len(joined),
         coordinates='SLAM raw right/down/forward; Twc maps camera to world; unmeasured relative scale',
         reference_median_depth=depth,world_scale_applied=1,calibration=calibration,
         descriptors='ORB60 exact R11 A32 rotated BRIEF256; not interchangeable with CPU ORB',
         binary=dict(endian='little',points='float32[N,3]',point_ids='uint64[N]',representative_descriptors='uint8[N,32]',
                     observation_descriptors='uint8[observations,32]'),
         representative='Actual observation minimizing median pairwise Hamming distance, first row breaks ties',
         source_keyframes_sha256=sha(a.source/'slam/keyframes/map_0/keyframes.csv'),
         source_observations_sha256=sha(a.source/'slam/keyframes/map_0/observations.csv')))
    trajectories=collections.defaultdict(list)
    for line in (a.source/'slam/Diagnostics_map0.txt').read_text().splitlines():
        fields=line.split()
        if fields:trajectories[int(Decimal(fields[0]))].append(raw_pose(fields))
    states=rows(a.source/'slam/TrackingStates.csv');canonical=[];duplicates=[]
    if len(states)!=len(features.index):raise ValueError('Missing tracking states')
    for stamp,poses in trajectories.items():
        if len(poses)>1:duplicates.append(dict(timestamp_ns=stamp,rows=len(poses),maximum_pose_difference=float(np.max(np.abs(np.asarray(poses)-poses[0])))))
    for row,state in zip(features.index,states):
        stamp=int(row['timestamp_ns']);candidates=trajectories.get(stamp,[])
        if int(state['frame_index'])!=int(row['frame_index']):raise ValueError('Tracking frame order mismatch')
        consistent=bool(candidates) and np.max(np.abs(np.asarray(candidates)-candidates[0]))<=1e-6
        valid=int(state['state_after'])==2 and consistent
        item=dict(frame_index=int(row['frame_index']),source_frame_index=int(row['source_frame_index']),timestamp_ns=stamp,
                  map_id=0,tracking_state=int(state['state_after']),pose_valid=int(valid),
                  reason='valid' if valid else ('ambiguous_duplicate_pose' if candidates and not consistent else 'not_tracking_or_no_pose'))
        item.update(pose_fields(candidates[0]) if valid else {'twc_%d%d'%(r,c):'' for r in range(4) for c in range(4)})
        canonical.append(item)
    write_rows(out/'slam_reference.csv',canonical)
    evidence=out/'source_evidence';evidence.mkdir()
    for name in ('Diagnostics_map0.txt','CameraTrajectory.txt','KeyFrameTrajectory.txt','TrackingStates.csv','status.json','output.log'):
        shutil.copy2(a.source/'slam'/name,evidence/name)
    save(out/'map_acceptance.json',dict(status='PASS',points=len(ids),keyframes=len(keys),observations=len(joined),
         maximum_raw_pixel_association_error=maximum,all_descriptors_from_verified_physical_records=True,
         raw_world_coordinates_unchanged=True,slam_reference_valid=sum(r['pose_valid'] for r in canonical),
         duplicate_trajectory_timestamps=duplicates,invalid_poses_not_interpolated=True))
    print('MAP_PASS',len(ids),'points',len(joined),'observations','duplicates',duplicates)

if __name__=='__main__':main()
