"""Resumable two-pass reconstruction. Run: python3 -m dense.reconstruct ..."""
import argparse
import collections
import csv
import datetime
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import cv2
import numpy as np
from .geometry import (backproject, camera_points, consistent_points, fit_inverse_depth,
                       sample_bilinear, valid_pose, VoxelMap)
from .ply import write_ply
from .video import camera_config, digest, prepare_video, working_image


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.part')
    tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)


def checked_write(path,image):
    if not cv2.imwrite(str(path),image):raise IOError('Cannot write '+str(path))


def stage_artifacts(root,stage):
    if stage=='track':
        paths=[root/'slam/status.json',root/'slam/keyframes/maps.csv']
        paths+=list((root/'slam/keyframes').glob('map_*/*.csv'))
        paths+=list((root/'slam').glob('Diagnostics_map*.txt'))
    elif stage=='select':
        paths=[root/'keyframes.json',root/'inputs/names.txt']+list((root/'inputs').glob('*.input.f32'))
        index=json.loads((root/'keyframes.json').read_text())
        paths += [root/frame[key] for m in index['maps'] for frame in m['frames']
                  for key in ['raw_rgb','rgb','valid_mask']]
    elif stage=='infer':
        paths=[root/'npu/worker.json',root/'npu/operator-profile.txt']+list((root/'npu').glob('*.output.f32'))
    else:
        paths=[root/'result.json',root/'reconstruction_keyframes.json']
        for name in ['result.json','dense.ply','sparse.ply','poses.json','replay.json','preview_features.json']:
            paths+=list(root.glob('map_*/'+name))
        paths+=list(root.glob('map_*/keyframes/*.depth*'))
    return {str(path.relative_to(root)):digest(path) for path in paths}


def select_frames(args,dataset):
    root=args.output
    sources={int(r['timestamp_ns']):r for r in csv.DictReader((dataset/'frames.csv').open())}
    prep_path=dataset/'preparation.json'
    preparation=json.loads(prep_path.read_text()) if prep_path.is_file() else None
    maps=[];wanted=collections.defaultdict(list)
    for maprow in csv.DictReader((root/'slam/keyframes/maps.csv').open()):
        mid=int(maprow['map_id']);folder=root/'slam/keyframes'/('map_%d'%mid)
        frames=[];last=-float('inf');buckets=set()
        for row in sorted(csv.DictReader((folder/'keyframes.csv').open()),key=lambda r:int(r['timestamp_ns'])):
            stamp=int(row['timestamp_ns'])
            if stamp not in sources:raise ValueError('Final keyframe has no exact source-frame match')
            source=sources[stamp];index=int(source['source_frame_index']);pts=float(source['mp4_pts_s'])
            pose=np.array([float(row['twc_%d%d'%(r,c)]) for r in range(4) for c in range(4)]).reshape(4,4)
            k=np.array([[float(row['fx']),0,float(row['cx'])],[0,float(row['fy']),float(row['cy'])],[0,0,1.]])
            bucket=int(np.floor(pts*2))
            selected=valid_pose(pose) and bucket not in buckets and pts-last>=.5-1e-8
            if selected:last=pts;buckets.add(bucket)
            item=dict(map_id=mid,keyframe_id=int(row['keyframe_id']),slam_frame_id=int(row['slam_frame_id']),
                      source_frame_index=index,timestamp_ns=stamp,source_pts_s=pts,twc=pose.tolist(),k=k.tolist(),
                      distortion=[float(row['d%d'%i]) for i in range(5)],selected=bool(selected))
            frames.append(item);wanted[index].append(item)
        maps.append(dict(map_id=mid,frames=frames,observations=str(folder/'observations.csv')))
    if not wanted:raise ValueError('SLAM produced no final valid keyframes')
    cap=cv2.VideoCapture(str(args.video))
    # Existing datasets used the original upright decode; new prepared datasets
    # explicitly rectify/rotate before SLAM and must repeat that exact transform.
    if preparation:cap.set(getattr(cv2,'CAP_PROP_ORIENTATION_AUTO',49),0)
    input_dir=root/'inputs';input_dir.mkdir(exist_ok=True)
    names=[]
    for index in range(max(wanted)+1):
        ok,bgr=cap.read()
        if not ok:raise ValueError('Original color decode ended before a real keyframe')
        for frame in wanted.get(index,[]):
            folder=root/('map_%d'%frame['map_id'])/'keyframes';folder.mkdir(parents=True,exist_ok=True)
            name='m%d_k%d'%(frame['map_id'],frame['keyframe_id'])
            raw=folder/(name+'.raw.png');work=folder/(name+'.rgb.png');mask_path=folder/(name+'.valid.png')
            checked_write(raw,bgr)
            if preparation:
                image,mask,k,roi,_=working_image(bgr,preparation['camera'],preparation['rotation_degrees'])
                if not np.allclose(k,frame['k'],atol=.01):raise ValueError('Keyframe intrinsic transform differs from preparation')
            else:
                if bgr.shape[:2]!=(720,960):raise ValueError('Existing dataset needs an explicit video transform manifest')
                k=np.asarray(frame['k']);dist=np.asarray(frame['distortion'])
                mx,my=cv2.initUndistortRectifyMap(k,dist,None,k,(960,720),cv2.CV_32FC1)
                image=cv2.remap(bgr,mx,my,cv2.INTER_LINEAR)
                mask=cv2.remap(np.full((720,960),255,np.uint8),mx,my,cv2.INTER_NEAREST)
                roi=(0,0,960,720)
            # Border removal includes the artificial letterbox and nearby patches.
            mask=cv2.erode(mask,np.ones((63,63),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)
            checked_write(work,image);checked_write(mask_path,mask)
            frame.update(name=name,raw_rgb=str(raw.relative_to(root)),rgb=str(work.relative_to(root)),
                         valid_mask=str(mask_path.relative_to(root)),roi=list(roi),raw_rgb_sha256=digest(raw))
            if frame['selected']:
                rgb=cv2.cvtColor(cv2.resize(image,(256,256),interpolation=cv2.INTER_CUBIC),cv2.COLOR_BGR2RGB)
                value=(rgb.astype(np.float32)/255.-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
                value=np.ascontiguousarray(value.transpose(2,0,1)[None]);value.tofile(input_dir/(name+'.input.f32'))
                frame['input_sha256']=digest(input_dir/(name+'.input.f32'));names.append(name)
    cap.release()
    (input_dir/'names.txt').write_text(''.join(n+'\n' for n in names))
    save(root/'keyframes.json',dict(maps=maps,selected=len(names),all_keyframes=sum(len(m['frames']) for m in maps),preparation=preparation,
                                   source='final stable SLAM atlas, exact source video frames'))
    return dict(maps=len(maps),selected=len(names),all_keyframes=sum(len(m['frames']) for m in maps))


def fit_maps(args):
    root=args.output;manifest=json.loads((root/'keyframes.json').read_text());reports=[]
    for mapinfo in manifest['maps']:
        mid=mapinfo['map_id'];folder=root/('map_%d'%mid);folder.mkdir(exist_ok=True)
        observations=collections.defaultdict(list)
        for r in csv.DictReader(Path(mapinfo['observations']).open()):observations[int(r['keyframe_id'])].append(r)
        usable=[];skipped=[];reference=None;sparse={}
        for frame in mapinfo['frames']:
            if not frame['selected']:continue
            name=frame['name'];pose=np.asarray(frame['twc']);k=np.asarray(frame['k'])
            obs=observations[frame['keyframe_id']]
            try:
                if len(obs)<20:raise ValueError('fewer_than_20_reliable_map_observations')
                prediction=np.fromfile(root/'npu'/(name+'.output.f32'),dtype='<f4')
                if prediction.size!=256*256:raise ValueError('NPU depth tensor shape mismatch')
                prediction=cv2.resize(prediction.reshape(256,256),(960,720),interpolation=cv2.INTER_LINEAR)
                mask=cv2.imread(str(root/frame['valid_mask']),cv2.IMREAD_GRAYSCALE)>0
                uv=np.array([[float(o['u']),float(o['v'])] for o in obs])
                xyz=np.array([[float(o[c]) for c in ['x','y','z']] for o in obs])
                z=camera_points(xyz,pose)[:,2]
                px=sample_bilinear(prediction,uv)
                allowed=sample_bilinear(mask.astype(np.float32),uv)>.99
                a,b,quality=fit_inverse_depth(px[allowed],z[allowed],seed=frame['keyframe_id'])
                inv=a*prediction+b
                limits=np.percentile(z[(z>0)&allowed],[5,95])
                with np.errstate(divide='ignore',invalid='ignore'):depth=1/inv
                mask &= np.isfinite(depth)&(inv>0)&(depth>limits[0]*.25)&(depth<limits[1]*4)
                if mask.sum()<100:raise ValueError('insufficient_valid_depth_pixels')
                if reference is None:reference=float(np.median(z[(z>0)&allowed]))
                np.save(folder/'keyframes'/(name+'.depth.npy'),depth.astype(np.float32))
                checked_write(folder/'keyframes'/(name+'.depth-valid.png'),mask.astype(np.uint8)*255)
                frame.update(fit=dict(slope=a,intercept=b,**quality))
                usable.append((frame,depth,mask,k,pose))
                color=cv2.cvtColor(cv2.imread(str(root/frame['rgb'])),cv2.COLOR_BGR2RGB)
                for o in obs:
                    u,v=int(round(float(o['u']))),int(round(float(o['v'])))
                    if 0<=u<960 and 0<=v<720 and mask[v,u]:
                        sparse[int(o['point_id'])]=([float(o[c]) for c in ['x','y','z']],color[v,u])
            except (ValueError,OSError) as e:
                skipped.append(dict(keyframe_id=frame['keyframe_id'],reason=str(e)))
        if reference is None:
            reports.append(dict(map_id=mid,status='SKIPPED',reason='no_valid_inverse_depth_fit',skipped=skipped));continue
        voxel=VoxelMap(reference*.01,capacity=args.capacity);seen=0;fused=0
        for i,(frame,depth,mask,k,pose) in enumerate(usable):
            candidates=[u for j,u in enumerate(usable) if j!=i and abs(j-i)<=4 and
                        np.linalg.norm(u[4][:3,3]-pose[:3,3])>reference*.01]
            views=[(u[1],u[2],u[3],u[4]) for u in candidates[:4]]
            if not views:
                skipped.append(dict(keyframe_id=frame['keyframe_id'],reason='no_neighbor_with_translation_parallax'));continue
            yy,xx=np.mgrid[0:720:args.pixel_step,0:960:args.pixel_step]
            ok=mask[yy,xx];uv=np.c_[xx[ok],yy[ok]];z=depth[yy[ok],xx[ok]]
            world=backproject(uv,z,k,pose)
            accepted=consistent_points(world,views);seen+=len(world)
            if not accepted.any():
                skipped.append(dict(keyframe_id=frame['keyframe_id'],reason='no_multiview_consistent_points'));continue
            color=cv2.cvtColor(cv2.imread(str(root/frame['rgb'])),cv2.COLOR_BGR2RGB)
            rgb=color[uv[:,1],uv[:,0]][accepted]
            voxel.add(world[accepted],rgb);fused+=1
            frame['consistent_pixels']=int(accepted.sum())
            print('FUSED',mid,frame['keyframe_id'],int(accepted.sum()),'voxels',len(voxel.counts),flush=True)
        xyz,rgb=voxel.arrays();xyz/=reference
        write_ply(folder/'dense.ply',xyz,rgb)
        sparse_xyz=np.asarray([v[0] for v in sparse.values()],np.float32).reshape(-1,3)/reference
        sparse_rgb=np.asarray([v[1] for v in sparse.values()],np.uint8).reshape(-1,3)
        write_ply(folder/'sparse.ply',sparse_xyz,sparse_rgb)
        poses=[]
        for frame in mapinfo['frames']:
            pose=np.asarray(frame['twc']).copy();pose[:3,3]/=reference
            poses.append(dict(keyframe_id=frame['keyframe_id'],source_frame_index=frame['source_frame_index'],
                              timestamp_ns=frame['timestamp_ns'],twc=pose.tolist()))
        save(folder/'poses.json',poses)
        preview=usable[len(usable)//2][0]
        preview_features=[[float(o['u']),float(o['v'])] for o in observations[preview['keyframe_id']]]
        save(folder/'preview_features.json',preview_features)
        report=dict(map_id=mid,status='GENERATED_REQUIRES_VISUAL_REVIEW',cloud='dense.ply',sparse='sparse.ply',poses='poses.json',
                    points=len(xyz),sparse_points=len(sparse_xyz),valid_depth_keyframes=len(usable),fused_keyframes=fused,
                    skipped=skipped,reference_median_depth_raw=reference,world_scale=1/reference,
                    voxel_edge=voxel.edge/reference,voxel_resolution_history=[e/reference for e in voxel.resolutions],
                    candidate_pixels=seen,meets_50000_point_gate=len(xyz)>=50000,
                    preview_rgb=str(Path(preview['rgb']).relative_to('map_%d'%mid)),
                    preview_features='preview_features.json',preview_source_frame=preview['source_frame_index'],
                    preview_keyframe=preview['keyframe_id'],
                    coordinate_system='SLAM right/down/forward; first valid sparse median depth = 1',
                    unobserved_regions='Only cross-view supported pixels; no hole filling or surfaces')
        save(folder/'result.json',report);reports.append(report)
    save(root/'reconstruction_keyframes.json',manifest)
    tracking=json.loads((root/'slam/status.json').read_text())
    peak=max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,tracking.get('peak_child_rss_kib',0))
    save(root/'result.json',dict(format_version=1,maps=reports,npu_model_sha256=digest(args.model),
                               video_sha256=digest(args.video),camera_source=str(args.camera),
                               camera_mode=camera_config(args.camera,960,720,args.approximate_camera)['mode'] if args.camera else 'explicit_approximate',
                               peak_rss_kib=peak,tracking_peak_rss_kib=tracking.get('peak_child_rss_kib'),
                               fusion_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                               status='GENERATED_REQUIRES_VISUAL_REVIEW'))
    from .replay import prepare_replay
    sources=(args.dataset or root/'dataset')/'frames.csv'
    for report in reports:
        if not report.get('points'):continue
        folder=root/('map_%d'%report['map_id'])
        report['replay_summary']=prepare_replay(root,folder,report['map_id'],sources)
        report['replay']='replay.json';save(folder/'result.json',report)
    result=json.loads((root/'result.json').read_text());result['maps']=reports;save(root/'result.json',result)
    return dict(maps=len(reports),points=sum(m.get('points',0) for m in reports))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',required=True,type=Path);p.add_argument('--camera',type=Path)
    p.add_argument('--approximate-camera',action='store_true');p.add_argument('--dataset',type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--slam-root',type=Path)
    p.add_argument('--fpga-host');p.add_argument('--network-runner',type=Path)
    p.add_argument('--worker',required=True,type=Path);p.add_argument('--model',required=True,type=Path)
    p.add_argument('--npu-acceptance',required=True,type=Path)
    p.add_argument('--stage',choices=['all','track','select','infer','fuse'],default='all')
    p.add_argument('--frames',type=int,default=0);p.add_argument('--pixel-step',type=int,default=2)
    p.add_argument('--capacity',type=int,default=2000000)
    args=p.parse_args()
    for key in ['video','camera','dataset','output','slam_root','network_runner','worker','model','npu_acceptance']:
        value=getattr(args,key)
        if value is not None:setattr(args,key,value.resolve())
    if not 1<=args.pixel_step<=8 or not 1<=args.capacity<=2000000:p.error('Invalid sampling/capacity')
    gate=json.loads(args.npu_acceptance.read_text())
    if gate['status']!='PASS' or gate['model']!='midas-v21-small' or gate['model_sha256']!=digest(args.model):
        raise ValueError('A real matching MiDaS NPU acceptance is required; CPU inference is not supported')
    args.output.mkdir(parents=True,exist_ok=True)
    lock=(args.output/'.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This modeling output already has a running owner; do not relaunch it')
    identity=dict(video_sha256=digest(args.video),model_sha256=digest(args.model),
                  camera_sha256=digest(args.camera) if args.camera else None,
                  approximate_camera=args.approximate_camera,dataset=str(args.dataset),frames=args.frames,
                  pixel_step=args.pixel_step,capacity=args.capacity,
                  dataset_manifest_sha256=digest(args.dataset/'frames.csv') if args.dataset else None,
                  worker_sha256=digest(args.worker),
                  code_sha256={n:digest(Path(__file__).parent/n) for n in ['reconstruct.py','geometry.py','video.py','ply.py','replay.py']})
    state_path=args.output/'state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(identity=identity,stages={})
    if state['identity']!=identity:raise ValueError('Resume input/configuration mismatch; choose another output directory')
    dataset=args.dataset or args.output/'dataset'
    stages=['track','select','infer','fuse'] if args.stage=='all' else [args.stage]
    start=time.monotonic()
    for stage in stages:
        if state['stages'].get(stage,{}).get('status')=='COMPLETED':
            for name,expected in state['stages'][stage].get('artifacts',{}).items():
                if not (args.output/name).is_file() or digest(args.output/name)!=expected:
                    raise ValueError('Completed stage artifact changed or is missing: '+name)
            print('RESUME_SKIP',stage,flush=True);continue
        tick=time.monotonic();state['stages'][stage]=dict(status='RUNNING');save(state_path,state)
        try:
            if stage=='track':
                existing=args.output/'slam/status.json'
                if existing.is_file():
                    retained=json.loads(existing.read_text())
                    expected=args.frames or len((dataset/'timestamps.txt').read_text().splitlines())
                    if retained.get('state')=='RUNNING':raise ValueError('Existing tracking process has no trustworthy completion')
                    if (retained.get('frames')!=expected or
                        Path(retained['dataset']).resolve()!=dataset.resolve() or
                        retained['camera_sha256']!=digest(args.camera if args.dataset else dataset/'camera.yaml')):
                        raise ValueError('Existing tracking pass cannot be reused for these inputs')
                    if retained.get('integration_pass') and retained.get('cpu_orb_calls')==0 and retained.get('exit_code')==0:
                        state['stages'][stage]=dict(status='COMPLETED',reused_accepted_tracking=True,
                                               result=dict(cpu_orb_calls=0,frames=retained['frames']),
                                               artifacts=stage_artifacts(args.output,stage))
                        save(state_path,state);continue
                    archive=args.output/'failed_attempts'/('slam_'+datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S%f'))
                    archive.parent.mkdir(exist_ok=True);existing.parent.rename(archive)
                if not args.dataset and not (dataset/'preparation.json').is_file():
                    prepare_video(args.video,args.camera,dataset,args.approximate_camera)
                if not args.slam_root or not args.network_runner or not args.fpga_host:raise ValueError('Tracking needs SLAM, runner and FPGA endpoint')
                env=os.environ.copy();env['ORB60_DENSE_EXPORT']=str(args.output/'slam/keyframes')
                if (dataset/'preparation.json').exists():
                    roi=json.loads((dataset/'preparation.json').read_text())['roi']
                    env['ORB60_VALID_ROI']=','.join(str(x) for x in roi)
                    env['ORB60_VALID_MASK']=str(dataset/'valid_mask.png')
                camera=dataset/'camera.yaml' if not args.dataset else args.camera
                command=[sys.executable,str(args.network_runner),'--slam-root',str(args.slam_root),
                         '--dataset',str(dataset),'--camera',str(camera),'--host',args.fpga_host,
                         '--frames',str(args.frames),'--platform','rk3588','--feature-mode','fpga-pipeline',
                         '--unpaced','--output',str(args.output/'slam')]
                subprocess.run(command,env=env,check=True)
                result=json.loads((args.output/'slam/status.json').read_text())
                if not result.get('integration_pass') or result.get('cpu_orb_calls')!=0:raise ValueError('FPGA tracking gate failed')
                result=dict(cpu_orb_calls=0,frames=result['frames'])
            elif stage=='select':
                tracking=json.loads((args.output/'slam/status.json').read_text())
                if not tracking.get('integration_pass') or tracking.get('cpu_orb_calls')!=0:raise ValueError('No accepted real FPGA tracking pass')
                result=select_frames(args,dataset)
            elif stage=='infer':
                with (args.output/'npu.log').open('w') as log:
                    subprocess.run([str(args.worker),str(args.model),str(args.output/'inputs'),
                                    str(args.output/'inputs/names.txt'),str(args.output/'npu')],
                                   stdout=log,stderr=subprocess.STDOUT,check=True)
                result=json.loads((args.output/'npu/worker.json').read_text())
            else:result=fit_maps(args)
            state['stages'][stage]=dict(status='COMPLETED',seconds=time.monotonic()-tick,result=result,
                                       artifacts=stage_artifacts(args.output,stage))
        except Exception as e:
            state['stages'][stage].update(status='FAILED',error=str(e),seconds=time.monotonic()-tick)
            save(state_path,state);raise
        save(state_path,state)
    state['last_run_seconds']=time.monotonic()-start
    state['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;save(state_path,state)


if __name__=='__main__':main()
