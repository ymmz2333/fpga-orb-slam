"""Host-only adapter regression; this does NOT execute or simulate PL."""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from .reference import samples,configuration,golden
from .fusion import PlFusion
from orb60.kv260.dense_fusion import Fusion,POINT

class Oracle:
    last_timings={}
    def project(self,depth,rgb,mask,k,twc):
        raw,_=golden(samples(depth,rgb,mask),configuration(k,twc));ids=raw[:,7]
        return dict(local=raw[:,:3].copy().view('<f4'),world=raw[:,3:6].copy().view('<f4'),
            rgb=np.c_[raw[:,6]&255,(raw[:,6]>>8)&255,(raw[:,6]>>16)&255].astype(np.uint8),
            uv=np.c_[ids%960,ids//960],source='HOST_CPU_REFERENCE_ONLY')

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    k=np.array([[600.,0,480],[0,600,360],[0,0,1]])
    y,x=np.mgrid[:720,:960];rgb=np.stack([x%256,y%256,(x+y)%256],axis=2).astype(np.uint8)
    base=Fusion(a.output/'original',lambda *args:None,'HOST_CPU_REFERENCE_ONLY')
    new=PlFusion(a.output/'adapter',lambda *args:None,'HOST_CPU_REFERENCE_ONLY',projector=Oracle())
    reports=[]
    for f in (base,new):
        f.references[0]=2.
        pose=np.eye(4);other=np.eye(4);other[0,3]=.1
        meta=dict(map_id=0,keyframe_id=1,source_frame_id=24,observations=[],twc=pose.tolist())
        item=dict(meta=meta,pose=pose,k=k,rgb=rgb,depth=np.full((720,960),2.),mask=np.ones((720,960),bool),published=False,fit={})
        o=dict(meta=dict(map_id=0),pose=other,k=k,depth=item['depth'],mask=item['mask'])
        f._publish(item,[o]);assert item['published'] and (0,1) in f.blocks
        assert f.blocks[(0,1)][0]['coordinates']=='anchor_camera_local'
        corrected=pose.copy();corrected[1,3]=.2;old_payload=f.blocks[(0,1)][1]
        f.update_pose(0,1,corrected);assert f.blocks[(0,1)][1]==old_payload
        assert f.blocks[(0,1)][0]['revision']==2
        reports.append(np.frombuffer(old_payload,POINT))
    old,new=reports;distance=cKDTree(old['xyz']).query(new['xyz'])[0]
    assert abs(len(old)-len(new))/len(old)<.02
    assert distance.max()<.016
    result=dict(status='HOST_ADAPTER_REFERENCE_PASS_NOT_HARDWARE',original_points=len(old),adapter_points=len(new),
                max_nearest_point_distance=float(distance.max()),local_blocks_preserved=True,pose_update_preserves_local_payload=True)
    (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
