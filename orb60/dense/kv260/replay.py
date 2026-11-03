"""PS dense replay and pose-updatable local blocks, independent of production RK guards."""
import argparse
import collections
import csv
import json
import hashlib
from pathlib import Path
import cv2
import numpy as np
from .common import digest,read_tensor,save,OUTPUT_SHAPE,checked_id,output_lock
from .prepare_replay import validate_manifest
from ..geometry import camera_points,backproject,consistent_points,fit_inverse_depth,sample_bilinear,valid_pose,VoxelMap
from ..ply import write_ply


def inside(root,path):
    root=Path(root).resolve();p=(root/path).resolve()
    try:p.relative_to(root)
    except ValueError:raise ValueError('Manifest path escapes data root')
    return p


def fuse_blocks(folder,blocks,reference,capacity,updates=None):
    """Always rebuild from camera-local points, never transform an already fused cloud."""
    voxel=VoxelMap(reference*.01,capacity=capacity);applied=[]
    for item in blocks:
        path=inside(folder,item['file'])
        if digest(path)!=item['sha256']:raise ValueError('Local block hash mismatch')
        with np.load(path,allow_pickle=False) as data:
            xyz=data['xyz_camera'];rgb=data['rgb'];pose=data['twc']
            if updates and item['name'] in updates:
                pose=np.asarray(updates[item['name']],np.float64);applied.append(item['name'])
            if not valid_pose(pose):raise ValueError('Invalid updated pose')
            world=xyz@pose[:3,:3].T+pose[:3,3]
            voxel.add(world,rgb)
    xyz,rgb=voxel.arrays();write_ply(folder/'dense.ply',xyz/reference,rgb)
    return {'points':len(xyz),'voxel_edge':voxel.edge/reference,'voxel_resolution_history':[x/reference for x in voxel.resolutions],
            'applied_pose_updates':applied}


def replay(inputs,depths,output,pixel_step=2,capacity=2000000):
    with output_lock(output):return _replay(inputs,depths,output,pixel_step,capacity)


def _replay(inputs,depths,output,pixel_step=2,capacity=2000000):
    inputs=Path(inputs);depths=Path(depths);output=Path(output)
    if not 1<=pixel_step<=8 or not 1<=capacity<=2000000:raise ValueError('Invalid sampling/capacity')
    manifest=validate_manifest(json.loads((inputs/'keyframes.json').read_text()))
    if (inputs/'preparation.json').exists():
        preparation=json.loads((inputs/'preparation.json').read_text())
        for name,expected in preparation.get('files',{}).items():
            if digest(inside(inputs,name))!=expected:raise ValueError('Saved replay input hash mismatch: '+name)
    worker=json.loads((depths/'worker.json').read_text())
    if worker['status'] not in {'HOST_REFERENCE_PASS','DPU_RUN_REQUIRES_NUMERICAL_GATE'}:raise ValueError('Incomplete worker run')
    names=[f['name'] for m in manifest['maps'] for f in m['frames'] if f['selected']]
    if [r['id'] for r in worker['frames']]!=names:raise ValueError('Worker/keyframe ordering mismatch')
    rows={r['id']:r for r in worker['frames']}
    stable_worker={'backend':worker['backend'],'model_sha256':worker['model_sha256'],
                   'frames':[{k:r[k] for k in ['id','input_sha256','output_sha256']} for r in worker['frames']]}
    identity={'manifest_sha256':digest(inputs/'keyframes.json'),'worker_identity_sha256':hashlib.sha256(json.dumps(stable_worker,sort_keys=True).encode()).hexdigest(),
              'pixel_step':pixel_step,'capacity':capacity,'geometry_sha256':digest(Path(__file__).parents[1]/'geometry.py')}
    output.mkdir(parents=True,exist_ok=True)
    if (output/'identity.json').exists() and json.loads((output/'identity.json').read_text())!=identity:raise ValueError('Fusion resume identity mismatch')
    save(output/'identity.json',identity);save(output/'result.json',{'status':'RUNNING','backend':worker['backend']});reports=[]
    for m in manifest['maps']:
        mid=m['map_id'];folder=output/('map_%d'%mid);(folder/'blocks').mkdir(parents=True,exist_ok=True)
        observations=collections.defaultdict(list)
        for r in csv.DictReader(inside(inputs,m['observations']).open()):observations[int(r['keyframe_id'])].append(r)
        usable=[];skipped=[];reference=None;sparse={}
        for frame in m['frames']:
            if not frame['selected']:continue
            name=checked_id(frame['name']);pose=np.array(frame['twc']);k=np.array(frame['k']);obs=observations[frame['keyframe_id']]
            path=depths/(name+'.output.f32');row=rows[name]
            if row['input_sha256']!=frame['input_sha256'] or digest(path)!=row['output_sha256']:raise ValueError('Frame provenance mismatch')
            prediction=read_tensor(path,OUTPUT_SHAPE)
            native_valid=prediction>0 if worker.get('family')=='fastdepth' else None
            image=cv2.imread(str(inside(inputs,frame['rgb'])));mask=cv2.imread(str(inside(inputs,frame['valid_mask'])),cv2.IMREAD_GRAYSCALE)
            if image is None or mask is None or image.shape[:2]!=mask.shape:raise ValueError('Damaged keyframe RGB/mask')
            h,w=mask.shape;mask=mask>0;prediction=cv2.resize(prediction,(w,h),interpolation=cv2.INTER_LINEAR)
            if native_valid is not None:mask &= cv2.resize(native_valid.astype(np.float32),(w,h),interpolation=cv2.INTER_LINEAR)>.999
            try:
                if len(obs)<20:raise ValueError('fewer_than_20_reliable_map_observations')
                uv=np.array([[float(o['u']),float(o['v'])] for o in obs]);xyz=np.array([[float(o[c]) for c in ['x','y','z']] for o in obs])
                z=camera_points(xyz,pose)[:,2];px=sample_bilinear(prediction,uv);allowed=sample_bilinear(mask.astype(np.float32),uv)>.99
                a,b,quality=fit_inverse_depth(px[allowed],z[allowed],seed=frame['keyframe_id'])
                inv=a*prediction+b;limits=np.percentile(z[(z>0)&allowed],[5,95])
                with np.errstate(divide='ignore',invalid='ignore'):depth=1/inv
                mask &= np.isfinite(depth)&(inv>0)&(depth>limits[0]*.25)&(depth<limits[1]*4)
                if mask.sum()<100:raise ValueError('insufficient_valid_depth_pixels')
                if reference is None:reference=float(np.median(z[(z>0)&allowed]))
                fit={'name':name,'slope':a,'intercept':b,**quality}
                usable.append((frame,depth,mask,k,pose,image,fit))
                color=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
                for o in obs:
                    u,v=int(round(float(o['u']))),int(round(float(o['v'])))
                    if 0<=u<w and 0<=v<h and mask[v,u]:sparse[int(o['point_id'])]=([float(o[c]) for c in ['x','y','z']],color[v,u])
            except ValueError as e:skipped.append({'name':name,'reason':str(e)})
        if reference is None:
            reports.append({'map_id':mid,'status':'NO_VALID_DEPTH','skipped':skipped});continue
        blocks=[];fits=[]
        for i,(frame,depth,mask,k,pose,image,fit) in enumerate(usable):
            candidates=[u for j,u in enumerate(usable) if j!=i and abs(j-i)<=4 and np.linalg.norm(u[4][:3,3]-pose[:3,3])>reference*.01]
            views=[(u[1],u[2],u[3],u[4]) for u in candidates[:4]]
            if not views:skipped.append({'name':frame['name'],'reason':'no_neighbor_with_translation_parallax'});continue
            h,w=mask.shape;yy,xx=np.mgrid[0:h:pixel_step,0:w:pixel_step];ok=mask[yy,xx];uv=np.c_[xx[ok],yy[ok]];z=depth[yy[ok],xx[ok]]
            world=backproject(uv,z,k,pose);accepted=consistent_points(world,views)
            if not accepted.any():skipped.append({'name':frame['name'],'reason':'no_multiview_consistent_points'});continue
            camera=camera_points(world[accepted],pose).astype(np.float32);rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)[uv[:,1],uv[:,0]][accepted]
            path=folder/'blocks'/(frame['name']+'.npz')
            with path.with_suffix('.part').open('wb') as stream:np.savez_compressed(stream,xyz_camera=camera,rgb=rgb,twc=pose)
            path.with_suffix('.part').replace(path)
            blocks.append({'name':frame['name'],'keyframe_id':frame['keyframe_id'],'timestamp_ns':frame['timestamp_ns'],
                           'map_id':mid,'file':str(path.relative_to(folder)).replace('\\','/'),'sha256':digest(path),'points':len(camera),
                           'depth_sha256':rows[frame['name']]['output_sha256']})
            fits.append(fit);print('LOCAL_BLOCK',mid,frame['name'],len(camera),flush=True)
        if not blocks:
            reports.append({'map_id':mid,'status':'NO_MULTIVIEW_SUPPORT','valid_depth_keyframes':len(usable),'skipped':skipped});continue
        fused=fuse_blocks(folder,blocks,reference,capacity)
        sparse_xyz=np.array([v[0] for v in sparse.values()],np.float32).reshape(-1,3)/reference
        sparse_rgb=np.array([v[1] for v in sparse.values()],np.uint8).reshape(-1,3)
        write_ply(folder/'sparse.ply',sparse_xyz,sparse_rgb)
        save(folder/'poses.json',[{'name':f['name'],'timestamp_ns':f['timestamp_ns'],'twc':f['twc']} for f in m['frames']])
        save(folder/'blocks.json',{'map_id':mid,'reference':reference,'blocks':blocks,'fits':fits,'capacity':capacity,
                                  'support_policy':'At least one neighboring view; pose corrections update fusion only; re-filter after large corrections.'})
        report={'map_id':mid,'status':'HOST_REPLAY_PASS' if worker['backend']!='dpu' else 'DPU_REPLAY_REQUIRES_BOARD_ACCEPTANCE',
                'backend':worker['backend'],'valid_depth_keyframes':len(usable),'fused_keyframes':len(blocks),'skipped':skipped,
                'reference_median_depth_raw':reference,'coordinate_system':'SLAM right/down/forward; relative scale, first median sparse depth = 1',**fused}
        save(folder/'result.json',report);reports.append(report)
    expected='DPU_REPLAY_REQUIRES_BOARD_ACCEPTANCE' if worker['backend']=='dpu' else 'HOST_REPLAY_PASS'
    result={'status':expected if reports and all(m['status']==expected for m in reports) else 'REPLAY_INCOMPLETE',
            'backend':worker['backend'],'hardware_inference_verified':worker['hardware_inference_verified'],'maps':reports,
            'identity':identity,'selected_keyframes':len(names)}
    save(output/'result.json',result);return result


def update_poses(folder,updates):
    folder=Path(folder);index=json.loads((folder/'blocks.json').read_text());updates=json.loads(Path(updates).read_text())
    if updates['map_id']!=index['map_id']:raise ValueError('Pose update belongs to another map')
    known={b['name'] for b in index['blocks']};changes=updates['poses']
    if not set(changes).issubset(known):raise ValueError('Unknown keyframe in pose update')
    # Validate all changes before rewriting the PLY.
    for pose in changes.values():
        if not valid_pose(np.asarray(pose)):raise ValueError('Invalid updated pose')
    cumulative=dict(index.get('pose_overrides',{}));cumulative.update(changes)
    result=fuse_blocks(folder,index['blocks'],index['reference'],index['capacity'],cumulative)
    index['pose_overrides']=cumulative;save(folder/'blocks.json',index);save(folder/'pose_update.json',result)
    if (folder/'result.json').exists():
        report=json.loads((folder/'result.json').read_text());report.update(result,poses_corrected=True);save(folder/'result.json',report)
    if (folder/'poses.json').exists():
        poses=json.loads((folder/'poses.json').read_text())
        for pose in poses:
            if pose['name'] in cumulative:pose['twc']=cumulative[pose['name']]
        save(folder/'poses.json',poses)
    return result


def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    r=s.add_parser('fuse')
    for key in ['inputs','depths','output']:r.add_argument('--'+key,type=Path,required=True)
    r.add_argument('--pixel-step',type=int,default=2);r.add_argument('--capacity',type=int,default=2000000)
    u=s.add_parser('update-poses');u.add_argument('--folder',type=Path,required=True);u.add_argument('--updates',type=Path,required=True)
    a=vars(p.parse_args());cmd=a.pop('command')
    try:result=replay(**a) if cmd=='fuse' else update_poses(**a)
    except Exception as e:
        if cmd=='fuse':save(a['output']/'result.json',{'status':'FAILED','error':repr(e)})
        raise
    print(json.dumps(result,ensure_ascii=False))
    if result.get('status')=='REPLAY_INCOMPLETE':raise SystemExit(1)

if __name__=='__main__':main()
