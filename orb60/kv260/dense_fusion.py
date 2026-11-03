"""PS-side colored point blocks; depth inference and GPU display are separate jobs."""
import json
import csv
import hashlib
from pathlib import Path
import cv2
import numpy as np
from orb60.dense.geometry import camera_points,backproject,fit_inverse_depth,sample_bilinear,consistent_points,VoxelMap,valid_pose
from orb60.dense.ply import write_ply

POINT=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))])


def save(path,value):
    path=Path(path);part=path.with_suffix('.part');part.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');part.replace(path)


class Fusion:
    def __init__(self,folder,publish,backend,max_blocks=128,voxel_class=VoxelMap):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=False)
        self.publish=publish;self.backend=backend;self.max_blocks=max_blocks
        self.previous=[];self.references={};self.blocks={};self.frames=0
        self.finalized_map=None;self.finalized_keys=set()
        self.voxel_class=voxel_class

    def process(self,meta,bgr,prediction,k,distortion):
        pose=np.asarray(meta['twc'],float);obs=np.asarray(meta['observations'],float);mid=int(meta['map_id'])
        if not valid_pose(pose) or obs.ndim!=2 or obs.shape[1]<5 or len(obs)<20 or not np.isfinite(obs).all():raise ValueError('Valid pose and >=20 finite sparse observations required')
        if k.shape!=(3,3) or not np.isfinite(k).all() or min(k[0,0],k[1,1])<=0:raise ValueError('Invalid camera intrinsics')
        if bgr.shape!=(720,960,3) or bgr.dtype!=np.uint8:raise ValueError('Paired 960x720 BGR frame required')
        if prediction.shape!=(256,256) or not np.isfinite(prediction).all():raise ValueError('Finite inverse depth required')
        mx,my=cv2.initUndistortRectifyMap(k,np.asarray(distortion),None,k,(960,720),cv2.CV_32FC1)
        bgr=cv2.remap(bgr,mx,my,cv2.INTER_LINEAR);rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
        mask=cv2.remap(np.full((720,960),255,np.uint8),mx,my,cv2.INTER_NEAREST)
        mask=cv2.erode(mask,np.ones((63,63),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
        prediction=cv2.resize(prediction,(960,720),interpolation=cv2.INTER_LINEAR)
        z=camera_points(obs[:,2:5],pose)[:,2];values=sample_bilinear(prediction,obs[:,:2]);valid=sample_bilinear(mask.astype(np.float32),obs[:,:2])>.99
        a,b,quality=fit_inverse_depth(values[valid],z[valid],seed=abs(int(meta['keyframe_id'])))
        inv=a*prediction+b
        with np.errstate(divide='ignore',invalid='ignore'):depth=1/inv
        limits=np.percentile(z[valid&(z>0)],[5,95]);mask &= np.isfinite(depth)&(inv>0)&(depth>limits[0]*.25)&(depth<limits[1]*4)
        if mask.sum()<100:raise ValueError('Insufficient valid depth')
        self.references.setdefault(mid,float(np.median(z[valid&(z>0)])))
        item=dict(meta=dict(meta),pose=pose,k=k,rgb=rgb,depth=depth,mask=mask,published=False,fit={'slope':a,'intercept':b,**quality})
        self.previous=[old for old in self.previous if old['meta']['map_id']==mid][-4:]
        for old in self.previous:
            if not old['published']:self._publish(old,[item])
        self._publish(item,self.previous);self.previous.append(item);self.frames+=1

    def _publish(self,item,others):
        meta=item['meta'];mid=int(meta['map_id']);key=(mid,int(meta['keyframe_id']));ref=self.references[mid]
        views=[(o['depth'],o['mask'],o['k'],o['pose']) for o in others if np.linalg.norm(o['pose'][:3,3]-item['pose'][:3,3])>ref*.01]
        if not views:return
        yy,xx=np.mgrid[0:720:2,0:960:2];ok=item['mask'][yy,xx];uv=np.c_[xx[ok],yy[ok]]
        world=backproject(uv,item['depth'][yy[ok],xx[ok]],item['k'],item['pose']);good=consistent_points(world,views)
        if good.sum()<100:return
        if key not in self.blocks and len(self.blocks)>=self.max_blocks:raise RuntimeError('Dense block capacity reached')
        voxel=self.voxel_class(ref*.004,capacity=12000)
        voxel.add(camera_points(world[good],item['pose']),item['rgb'][uv[good,1],uv[good,0]])
        xyz,rgb=voxel.arrays();points=np.empty(len(xyz),POINT);points['xyz']=xyz;points['rgb']=rgb
        payload=points.tobytes();metadata={key:value for key,value in meta.items() if key!='observations'}
        metadata.update(event='chunk',points=len(points),twc=item['pose'].tolist(),revision=1,coordinates='anchor_camera_local',voxel_edge=voxel.edge,
                        source=self.backend,fit=item['fit'],source_frame_index=int(meta['source_frame_id']),payload_sha256=hashlib.sha256(payload).hexdigest())
        stem='m%d_f%d'%(mid,int(meta['source_frame_id']));(self.folder/(stem+'.bin')).write_bytes(payload)
        save(self.folder/(stem+'.json'),metadata)
        save(self.folder/(stem+'.anchors.json'),{'observations':meta['observations'],'twc':meta['twc']})
        self.blocks[key]=(metadata,payload,stem);self.publish(metadata,payload);item['published']=True

    def update_pose(self,map_id,anchor_id,pose):
        pose=np.asarray(pose,float)
        if not valid_pose(pose):raise ValueError('Invalid corrected pose')
        key=(int(map_id),int(anchor_id))
        if key not in self.blocks:raise ValueError('Unknown map/anchor')
        meta,payload,stem=self.blocks[key];meta=dict(meta,twc=pose.tolist(),revision=meta['revision']+1)
        save(self.folder/(stem+'.json'),meta);self.blocks[key]=(meta,payload,stem);self.publish(meta,payload)

    def export(self,map_id,path):
        if map_id not in self.references:raise ValueError('Unknown map')
        voxel=self.voxel_class(self.references[map_id]*.004,capacity=2000000)
        for (mid,_),(meta,payload,_) in self.blocks.items():
            if mid!=map_id:continue
            if self.finalized_map==mid and (mid,int(meta['keyframe_id'])) not in self.finalized_keys:continue
            points=np.frombuffer(payload,POINT);pose=np.asarray(meta['twc'])
            voxel.add(points['xyz']@pose[:3,:3].T+pose[:3,3],points['rgb'])
        xyz,rgb=voxel.arrays()
        if not len(xyz):raise ValueError('No multi-view-supported RGB points')
        write_ply(Path(path),xyz,rgb);return {'map_id':map_id,'points':len(xyz),'backend':self.backend,'coordinates':'raw SLAM relative world'}

    def finalize(self,tracking):
        tracking=Path(tracking);folder=tracking/'map';mid=int((folder/'map_id.txt').read_text())
        def rows(path):
            with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
        finals={int(row['slam_timestamp_ns']):np.array([[float(row['twc_%d%d'%(r,c)]) for c in range(4)] for r in range(4)])
                for row in rows(folder/'final_frames.csv') if int(row['map_id'])==mid}
        journal={int(row['source_frame_id']):int(row['slam_timestamp_ns']) for row in rows(tracking/'frames.csv')}
        landmarks={int(row['point_id']):[float(row[k]) for k in ('x','y','z')] for row in rows(folder/'points.csv')}
        accepted=[];skipped=[]
        for key,(meta,payload,stem) in list(self.blocks.items()):
            if key[0]!=mid:continue
            try:
                pose=finals[journal[int(meta['source_frame_id'])]]
                if not valid_pose(pose):raise ValueError('Invalid optimized anchor pose')
                anchor=json.loads((self.folder/(stem+'.anchors.json')).read_text(encoding='utf-8'));obs=np.asarray(anchor['observations'],float)
                payload=(self.folder/(stem+'.bin')).read_bytes()
                original=json.loads((self.folder/(stem+'.json')).read_text(encoding='utf-8'))
                if hashlib.sha256(payload).hexdigest()!=original['payload_sha256']:raise ValueError('Corrupted original local block')
                if obs.shape[1]!=6:raise ValueError('Final correction requires landmark IDs')
                common=[i for i,row in enumerate(obs) if int(row[5]) in landmarks]
                if len(common)<20:raise ValueError('Fewer than 20 retained common landmarks')
                old_z=camera_points(obs[common,2:5],np.asarray(anchor['twc']))[:,2]
                new_z=camera_points(np.array([landmarks[int(obs[i,5])] for i in common]),pose)[:,2]
                valid=np.isfinite(old_z)&np.isfinite(new_z)&(old_z>1e-6)&(new_z>1e-6)
                a,b,quality=fit_inverse_depth(1/old_z[valid],new_z[valid],seed=abs(key[1]))
                points=np.frombuffer(payload,POINT);local=points['xyz'].astype(float);old=local[:,2]
                with np.errstate(divide='ignore',invalid='ignore'):new=1/(a/old+b)
                limits=np.percentile(new_z[valid],[5,95]);good=np.isfinite(local).all(axis=1)&np.isfinite(new)&(old>1e-6)&(new>limits[0]*.25)&(new<limits[1]*4)
                if good.sum()<100:raise ValueError('Insufficient final RGB points')
                local=local[good];local*=new[good,None]/local[:,2:3]
                corrected=np.empty(len(local),POINT);corrected['xyz']=local;corrected['rgb']=points['rgb'][good]
                data=corrected.tobytes();updated=dict(meta,twc=pose.tolist(),revision=meta['revision']+1,points=len(corrected),
                                                     final_inverse_depth_fit={'slope':a,'intercept':b,**quality},optimized_anchor=True,payload_sha256=hashlib.sha256(data).hexdigest())
                (self.folder/(stem+'.final.bin')).write_bytes(data);save(self.folder/(stem+'.final.json'),updated)
                self.blocks[key]=(updated,data,stem);self.publish(updated,data);self.finalized_keys.add(key);accepted.append(stem)
            except (ValueError,KeyError,OSError) as error:skipped.append({'block':stem,'reason':str(error)})
        if not accepted:raise ValueError('No point blocks supported by final optimized poses and landmarks')
        self.finalized_map=mid;report={'map_id':mid,'accepted':accepted,'skipped':skipped,'original_local_blocks_preserved':True}
        save(self.folder/'final_pose_update.json',report);return report
