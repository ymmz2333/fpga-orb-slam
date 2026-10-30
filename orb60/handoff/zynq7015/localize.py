"""Frozen-map CPU matching/PnP reference; all input descriptors must come from PL."""
import argparse
from pathlib import Path
import time
import cv2
import numpy as np
from common import Features,feature_points,load,save,write_rows,pose_fields,pose_error,sha

DEFAULT=dict(hamming_max=64,ratio=.8,min_matches=15,min_inliers=15,reprojection_px=3.,
             iterations=200,confidence=.999,seed=1729,min_inlier_ratio=.3)

class Localizer:
    def __init__(self,folder,config=None):
        self.folder=Path(folder);self.map=load(self.folder/'map.json');self.config=dict(DEFAULT,**(config or {}))
        self.xyz=np.fromfile(self.folder/'points.bin',dtype='<f4').reshape(-1,3)
        self.ids=np.fromfile(self.folder/'point_ids.bin',dtype='<u8')
        self.descriptors=np.fromfile(self.folder/'representative_descriptors.bin',dtype=np.uint8).reshape(-1,32)
        self.k=np.array(self.map['calibration']['k'],np.float64)
        self.dist=np.array(self.map['calibration']['distortion'],np.float64)
        self.matcher=cv2.BFMatcher(cv2.NORM_HAMMING);cv2.setNumThreads(1)

    def solve(self,records,frame_index):
        c=self.config;start=time.perf_counter();uv=feature_points(records)
        nearest=self.matcher.knnMatch(np.ascontiguousarray(records['descriptor']),self.descriptors,k=2)
        accepted=[]
        for pair in nearest:
            if len(pair)==2 and pair[0].distance<=c['hamming_max'] and pair[0].distance<c['ratio']*pair[1].distance:
                accepted.append(pair[0])
        accepted.sort(key=lambda m:(m.distance,m.trainIdx,m.queryIdx))
        unique=[];used=set()
        for match in accepted:
            if match.trainIdx not in used:used.add(match.trainIdx);unique.append(match)
        result=dict(pose_valid=0,reason='insufficient_matches',matches=len(unique),inliers=0,median_reprojection_px=None)
        if len(unique)<c['min_matches']:return result,None
        obj=self.xyz[[m.trainIdx for m in unique]].astype(np.float64)
        image=cv2.undistortPoints(uv[[m.queryIdx for m in unique]].astype(np.float64).reshape(-1,1,2),self.k,self.dist,P=self.k).reshape(-1,2)
        cv2.setRNGSeed(c['seed']+int(frame_index))
        ok,rvec,tvec,inliers=cv2.solvePnPRansac(obj,image,self.k,None,iterationsCount=c['iterations'],
            reprojectionError=c['reprojection_px'],confidence=c['confidence'],flags=cv2.SOLVEPNP_EPNP)
        if not ok or inliers is None:result['reason']='ransac_failed';return result,None
        keep=inliers.ravel();result['inliers']=len(keep)
        if len(keep)<c['min_inliers'] or len(keep)/len(unique)<c['min_inlier_ratio']:
            result['reason']='insufficient_inliers';return result,None
        initial_rvec=rvec.copy();initial_tvec=tvec.copy()
        ok,rvec,tvec=cv2.solvePnP(obj[keep],image[keep],self.k,None,rvec,tvec,True,flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or not np.isfinite(rvec).all() or not np.isfinite(tvec).all():result['reason']='refinement_failed';return result,None
        rotation,_=cv2.Rodrigues(rvec);camera=obj[keep]@rotation.T+tvec.ravel()
        projected,_=cv2.projectPoints(obj[keep],rvec,tvec,self.k,None)
        error=np.linalg.norm(projected.reshape(-1,2)-image[keep],axis=1)
        median=float(np.median(error));result['median_reprojection_px']=median
        if np.mean(camera[:,2]>0)<.95 or median>c['reprojection_px']:
            result['reason']='invalid_projection';return result,None
        twc=np.eye(4);twc[:3,:3]=rotation.T;twc[:3,3]=-rotation.T@tvec.ravel()
        result.update(pose_valid=1,reason='valid',seconds=time.perf_counter()-start,**pose_fields(twc))
        case=dict(object=obj[keep],image=image[keep],initial_rvec=initial_rvec.ravel(),initial_tvec=initial_tvec.ravel(),
                  twc=twc,k=self.k,inlier_point_ids=self.ids[[unique[i].trainIdx for i in keep]])
        return result,case

def run(map_folder,golden,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    localizer=Localizer(map_folder);features=Features(golden);results=[];cases=[];start=time.perf_counter()
    for i,frame in enumerate(features.index):
        frame_start=time.perf_counter()
        result,case=localizer.solve(features.frame(i),i)
        row=dict(frame_index=i,source_frame_index=int(frame['source_frame_index']),timestamp_ns=int(frame['timestamp_ns']),map_id=0)
        row.update(result)
        for r in range(4):
            for c in range(4):row.setdefault('twc_%d%d'%(r,c),'')
        row['seconds']=time.perf_counter()-frame_start
        results.append(row)
        if case is not None and i%100==0:cases.append((i,case))
        if (i+1)%200==0:print('LOCALIZE',i+1,'valid',sum(r['pose_valid'] for r in results),'seconds',round(time.perf_counter()-start,2),flush=True)
    write_rows(output/'trajectory.csv',results)
    casefolder=output/'pnp_cases';casefolder.mkdir()
    inventory=[]
    for number,(index,case) in enumerate(cases[:20]):
        name='case_%02d'%number;csvrows=[]
        for xyz,uv,pid in zip(case['object'],case['image'],case['inlier_point_ids']):
            csvrows.append(dict(point_id=int(pid),x=xyz[0],y=xyz[1],z=xyz[2],u=uv[0],v=uv[1]))
        write_rows(casefolder/(name+'.csv'),csvrows)
        save(casefolder/(name+'.json'),{key:value.tolist() if isinstance(value,np.ndarray) else value for key,value in case.items()
             if key not in ('object','image','inlier_point_ids')})
        inventory.append(dict(name=name,frame_index=index,correspondences=len(csvrows)))
    save(casefolder/'index.json',inventory)
    save(output/'configuration.json',dict(parameters=localizer.config,opencv=cv2.__version__,numpy=np.__version__,
         coordinates=localizer.map['coordinates'],map_folder='map',descriptor_source='golden physical FPGA records',
         implementation_sha256=sha(__file__),map_sha256=sha(Path(map_folder)/'map.json'),
         golden_features_sha256=sha(Path(golden)/'features.bin'),
         deterministic='single OpenCV thread, per-frame fixed RANSAC seed, fixed point order'))
    save(output/'run_report.json',dict(status='GENERATED_REQUIRES_INDEPENDENT_CHECK',frames=len(results),
         valid=sum(r['pose_valid'] for r in results),seconds=time.perf_counter()-start,pnp_cases=len(inventory),
         cpu_orb_calls=0,scope='CPU matching and pose only; no new map or ORB extraction'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--map',type=Path,required=True);p.add_argument('--golden',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.map,a.golden,a.output)
