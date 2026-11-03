"""Opt-in Fusion subclass; PS fit, consistency, voxels, anchors remain intact."""
import hashlib
import numpy as np
from orb60.kv260.dense_fusion import Fusion,POINT,save
from orb60.dense.geometry import consistent_points

class PlFusion(Fusion):
    def __init__(self,*args,projector,**kwargs):
        super().__init__(*args,**kwargs);self.projector=projector;self.projection_timings=[]

    def _publish(self,item,others):
        meta=item['meta'];mid=int(meta['map_id']);key=(mid,int(meta['keyframe_id']));ref=self.references[mid]
        views=[(o['depth'],o['mask'],o['k'],o['pose']) for o in others if np.linalg.norm(o['pose'][:3,3]-item['pose'][:3,3])>ref*.01]
        if not views:return
        result=self.projector.project(item['depth'],item['rgb'],item['mask'],item['k'],item['pose'])
        self.projection_timings.append(dict(source_frame_id=meta['source_frame_id'],**self.projector.last_timings))
        good=consistent_points(result['world'],views)
        if good.sum()<100:return
        if key not in self.blocks and len(self.blocks)>=self.max_blocks:raise RuntimeError('Dense block capacity reached')
        voxel=self.voxel_class(ref*.004,capacity=12000)
        # Keep the camera-local blocks required by later corrected poses.
        voxel.add(result['local'][good],result['rgb'][good]);xyz,rgb=voxel.arrays()
        points=np.empty(len(xyz),POINT);points['xyz']=xyz;points['rgb']=rgb;payload=points.tobytes()
        metadata={key:value for key,value in meta.items() if key!='observations'}
        metadata.update(event='chunk',points=len(points),twc=item['pose'].tolist(),revision=1,coordinates='anchor_camera_local',
                        voxel_edge=voxel.edge,source=self.backend,geometry_backend=result['source'],fit=item['fit'],
                        source_frame_index=int(meta['source_frame_id']),payload_sha256=hashlib.sha256(payload).hexdigest())
        stem='m%d_f%d'%(mid,int(meta['source_frame_id']));(self.folder/(stem+'.bin')).write_bytes(payload)
        save(self.folder/(stem+'.json'),metadata);save(self.folder/(stem+'.anchors.json'),{'observations':meta['observations'],'twc':meta['twc']})
        self.blocks[key]=(metadata,payload,stem);self.publish(metadata,payload);item['published']=True
