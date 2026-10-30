"""Bounded visualization state; display transforms never change exported SLAM data."""
from collections import deque
import numpy as np

WORLD_TO_VIEW=np.array([[1,0,0],[0,0,1],[0,-1,0]],dtype=np.float32)


def view_points(points):return np.asarray(points,dtype=np.float32)@WORLD_TO_VIEW.T


class Scene:
    def __init__(self):self.reset()

    def reset(self):
        self.map_id=None;self.points=np.empty((0,3),np.float32);self.point_ids=np.empty(0,np.uint64)
        self.keyframes=np.empty((0,4,4),np.float32);self.pose=np.eye(4,dtype=np.float32)
        self.pose_valid=False;self.meta={};self.trace=deque(maxlen=5000);self.segments=deque(maxlen=10000)
        self.last_index=-1;self.previous_valid=False;self.last_position=None

    def apply(self,snapshot):
        meta=snapshot.meta
        if meta.get('event')=='status':return False
        if self.map_id!=meta['map_id']:
            self.reset();self.map_id=meta['map_id']
        if meta['frame_index']<=self.last_index:return False
        self.last_index=meta['frame_index'];self.meta=meta
        if meta['map_full']:
            self.points=snapshot.points['xyz'].copy();self.point_ids=snapshot.points['id'].copy()
            self.keyframes=snapshot.keyframes['twc'].copy()
        self.pose=np.asarray(meta['pose_twc'],dtype=np.float32).reshape(4,4)
        self.pose_valid=bool(meta['pose_valid'] and meta['state']==2)
        if self.pose_valid:
            p=self.pose[:3,3].copy();self.trace.append((meta['timestamp_ns'],self.pose.copy()))
            if self.previous_valid:self.segments.extend((self.last_position,p))
            self.last_position=p
        self.previous_valid=self.pose_valid
        return True


def frustum_lines(poses,size):
    poses=np.asarray(poses,dtype=np.float32).reshape(-1,4,4)
    if not len(poses):return np.empty((0,3),np.float32)
    corners=np.array([[0,0,0],[-1,-.75,1.3],[1,-.75,1.3],[1,.75,1.3],[-1,.75,1.3]],np.float32)*size
    pairs=np.array([0,1,0,2,0,3,0,4,1,2,2,3,3,4,4,1])
    transformed=np.einsum('nij,kj->nki',poses[:,:3,:3],corners)+poses[:,:3,3,None].transpose(0,2,1)
    return view_points(transformed[:,pairs,:].reshape(-1,3))


def export_ply(path,scene):
    with open(path,'w',encoding='ascii') as f:
        f.write('ply\nformat ascii 1.0\ncomment ORB SLAM world coordinates, uncalibrated monocular scale\n')
        f.write(f'element vertex {len(scene.points)}\nproperty float x\nproperty float y\nproperty float z\nend_header\n')
        np.savetxt(f,scene.points,fmt='%.9g')
