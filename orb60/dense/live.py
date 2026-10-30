"""Actual FPGA SLAM and asynchronous NPU keyframe depth with incremental point chunks."""
import argparse
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import cv2
import numpy as np
from .geometry import camera_points,backproject,fit_inverse_depth,sample_bilinear,consistent_points,VoxelMap
from .live_server import DeltaServer
from .fpga_guard import verify as verify_fpga,verify_inputs

POINT=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))])


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(path,value):
    path=Path(path);tmp=path.with_suffix('.part');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)


class OnlineDepth:
    def __init__(self,args,server,sources,color_source=None):
        self.a=args;self.server=server;self.sources=sources;self.seen=set();self.previous=[]
        self.references={};self.chunks=[];self.skipped=[];self.npu_frames=0
        self.started=time.monotonic();self.first_chunk_seconds=None
        self.color_source=color_source
        self.cap=None if color_source else cv2.VideoCapture(str(args.video));self.next_index=0
        self.input=args.output/'inputs';self.output=args.output/'npu'
        self.input.mkdir();self.output.mkdir()
        self.log=(args.output/'npu.log').open('w')
        self.worker=subprocess.Popen([str(args.worker),str(args.model),str(self.input),'-',str(self.output)],
                                     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1)

    def color(self,index):
        if self.color_source:return self.color_source(index)
        if index<self.next_index:self.cap.release();self.cap=cv2.VideoCapture(str(self.a.video));self.next_index=0
        while self.next_index<index:
            if not self.cap.grab():raise ValueError('Original live keyframe source is unavailable')
            self.next_index+=1
        ok,bgr=self.cap.read();self.next_index=index+1
        if not ok or bgr.shape[:2]!=(720,960):raise ValueError('Live source must match explicit existing calibration')
        return bgr

    def process(self,path):
        frame=json.loads(path.read_text());self.seen.add(path.name)
        try:
            stamp=frame['timestamp_ns']
            if stamp not in self.sources:raise ValueError('Live keyframe has no exact source timestamp')
            source=self.sources[stamp];frame['source_frame_index']=int(source['source_frame_index'])
            frame['source_pts_s']=float(source['mp4_pts_s'])
            pose=np.array(frame['twc']);k=np.array(frame['k']);obs=np.array(frame['observations'],float)
            if len(obs)<20:raise ValueError('Fewer than 20 reliable live correspondences')
            raw=self.color(frame['source_frame_index'])
            mx,my=cv2.initUndistortRectifyMap(k,np.array(frame['distortion']),None,k,(960,720),cv2.CV_32FC1)
            bgr=cv2.remap(raw,mx,my,cv2.INTER_LINEAR)
            mask=cv2.remap(np.full((720,960),255,np.uint8),mx,my,cv2.INTER_NEAREST)
            mask=cv2.erode(mask,np.ones((63,63),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
            rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
            small=cv2.resize(rgb,(256,256),interpolation=cv2.INTER_CUBIC).astype(np.float32)/255.
            tensor=(small-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
            name='m%d_k%d'%(frame['map_id'],frame['keyframe_id'])
            np.ascontiguousarray(tensor.transpose(2,0,1)[None]).tofile(self.input/(name+'.input.f32'))
            self.worker.stdin.write(name+'\n');self.worker.stdin.flush()
            while True:
                line=self.worker.stdout.readline()
                if not line:raise RuntimeError('Persistent NPU worker stopped unexpectedly')
                self.log.write(line);self.log.flush()
                if line.startswith('NPU_FRAME '+name+' '):break
            self.npu_frames+=1
            prediction=np.fromfile(self.output/(name+'.output.f32'),dtype='<f4').reshape(256,256)
            prediction=cv2.resize(prediction,(960,720),interpolation=cv2.INTER_LINEAR)
            z=camera_points(obs[:,2:5],pose)[:,2];sample=sample_bilinear(prediction,obs[:,:2])
            valid=sample_bilinear(mask.astype(np.float32),obs[:,:2])>.99
            a,b,quality=fit_inverse_depth(sample[valid],z[valid],seed=frame['keyframe_id'])
            inv=a*prediction+b
            with np.errstate(divide='ignore',invalid='ignore'):depth=1/inv
            limits=np.percentile(z[valid&(z>0)],[5,95])
            mask &= np.isfinite(depth)&(inv>0)&(depth>limits[0]*.25)&(depth<limits[1]*4)
            mid=frame['map_id']
            if mid not in self.references:self.references[mid]=float(np.median(z[valid&(z>0)]))
            frame['fit']=dict(slope=a,intercept=b,**quality)
            item=dict(frame=frame,depth=depth,mask=mask,k=k,pose=pose,rgb=rgb,published=False)
            self.previous=[old for old in self.previous if old['frame']['map_id']==mid][-4:]
            for old in self.previous:
                if not old['published']:self.publish(old,[item])
            self.publish(item,self.previous)
            self.previous.append(item)
            save(self.a.output/'live_report.json',self.report())
        except ValueError as exc:
            self.skipped.append(dict(file=path.name,reason=str(exc)));print('LIVE_DEPTH_SKIP',path.name,str(exc),flush=True)

    def publish(self,item,others):
        frame=item['frame'];ref=self.references[frame['map_id']]
        views=[(o['depth'],o['mask'],o['k'],o['pose']) for o in others
               if np.linalg.norm(o['pose'][:3,3]-item['pose'][:3,3])>ref*.01]
        if not views:return
        yy,xx=np.mgrid[0:720:2,0:960:2];ok=item['mask'][yy,xx];uv=np.c_[xx[ok],yy[ok]]
        world=backproject(uv,item['depth'][yy[ok],xx[ok]],item['k'],item['pose'])
        good=consistent_points(world,views)
        if good.sum()<100:return
        local=camera_points(world[good],item['pose'])
        voxel=VoxelMap(ref*.004,capacity=12000)
        voxel.add(local,item['rgb'][uv[good,1],uv[good,0]])
        xyz,rgb=voxel.arrays();points=np.empty(len(xyz),dtype=POINT);points['xyz']=xyz;points['rgb']=rgb
        meta=dict(event='chunk',map_id=frame['map_id'],keyframe_id=frame['keyframe_id'],
                  timestamp_ns=frame['timestamp_ns'],source_frame_index=frame['source_frame_index'],
                  points=len(xyz),twc=frame['twc'],voxel_edge=voxel.edge,revision=1,
                  source='actual_rk3588_npu',fit=frame['fit'],coordinates='keyframe_camera_local')
        if getattr(self.a,'retain_anchor_observations',False):
            meta['_anchor_observations']=frame['observations']
        name='m%d_k%d'%(frame['map_id'],frame['keyframe_id'])
        if getattr(self.a,'frame_chunks',True):
            (self.a.output/'chunks'/(name+'.bin')).write_bytes(points.tobytes())
            save(self.a.output/'chunks'/(name+'.json'),meta)
        self.server.publish(meta,points.tobytes());item['published']=True
        elapsed=time.monotonic()-self.started
        if self.first_chunk_seconds is None:self.first_chunk_seconds=elapsed
        self.chunks.append(dict(map_id=meta['map_id'],keyframe_id=meta['keyframe_id'],points=len(xyz),seconds=elapsed,
                                source_frame_index=meta['source_frame_index']))
        print('LIVE_CHUNK',name,'points',len(xyz),'seconds',round(elapsed,3),flush=True)

    def report(self):
        return dict(state=self.server.state,npu_frames=self.npu_frames,chunks=self.chunks,skipped=self.skipped,
                    points=sum(c['points'] for c in self.chunks),first_chunk_seconds=self.first_chunk_seconds,
                    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    semantics='Provisional online map, per-keyframe chunks; final optimized reconstruction remains separate')

    def close(self,allow_empty=False):
        self.worker.stdin.close()
        for line in self.worker.stdout:self.log.write(line)
        code=self.worker.wait(timeout=30)
        if self.cap:self.cap.release()
        self.log.close()
        if code and not (allow_empty and self.npu_frames==0):raise RuntimeError('Persistent NPU worker failed: '+str(code))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['video','dataset','camera','slam-root','worker','model','npu-acceptance','network-runner','output']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--fpga-host',required=True);p.add_argument('--frames',type=int,default=0)
    p.add_argument('--executable',type=Path);p.add_argument('--library-directory',type=Path)
    p.add_argument('--fpga-client',type=Path,required=True)
    p.add_argument('--port',type=int,default=18769);p.add_argument('--linger',action='store_true');a=p.parse_args()
    for key,value in vars(a).items():
        if isinstance(value,Path):setattr(a,key,value.resolve())
    gate=json.loads(a.npu_acceptance.read_text())
    if gate['status']!='PASS' or gate['model_sha256']!=sha(a.model):raise ValueError('Matching physical NPU gate required')
    a.output.mkdir(parents=True,exist_ok=False)
    for name in ['keyframes_live','chunks']:(a.output/name).mkdir()
    sources={int(r['timestamp_ns']):r for r in csv.DictReader((a.dataset/'frames.csv').open())}
    server=DeltaServer(a.output,'127.0.0.1',a.port);processor=None;track=None;log=None
    (a.output/'controller.pid').write_text(str(os.getpid()))
    failure=None
    try:
        server.state='CHECKING_FPGA'
        save(a.output/'session.json',dict(state=server.state,port=a.port))
        proof=verify_fpga(a.fpga_client,a.fpga_host,a.dataset)
        save(a.output/'fpga_preflight.json',proof)
        save(a.output/'input_acceptance.json',verify_inputs(a.dataset))
    except Exception as exc:
        failure='FPGA startup verification failed: '+str(exc)
        server.state='ERROR';server.error=failure
        save(a.output/'session.json',dict(state='ERROR',error=failure,port=a.port))
        while a.linger and not (a.output/'stop').exists():time.sleep(.1)
        server.close();save(a.output/'done.json',dict(state='ERROR',error=failure))
        raise RuntimeError(failure)
    try:
        if (a.output/'stop').exists():
            server.state='CANCELLED';return
        processor=OnlineDepth(a,server,sources)
        env=os.environ.copy();env['ORB60_DENSE_LIVE_DIR']=str(a.output/'keyframes_live')
        env['ORB60_DENSE_EXPORT']=str(a.output/'final_keyframes')
        command=[sys.executable,str(a.network_runner),'--slam-root',str(a.slam_root),'--dataset',str(a.dataset),
                 '--camera',str(a.camera),'--host',a.fpga_host,'--frames',str(a.frames),'--platform','rk3588',
                 '--feature-mode','fpga-pipeline','--telemetry','--telemetry-fps','30','--cpu-affinity','4-7','--output',str(a.output/'slam')]
        if a.executable:command+=['--executable',str(a.executable)]
        if a.library_directory:command+=['--library-directory',str(a.library_directory)]
        log=(a.output/'tracking_runner.log').open('w')
        track=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        server.state='INITIALIZING';save(a.output/'session.json',dict(state='INITIALIZING',port=a.port,process_id=track.pid))
        while True:
            if track.poll() is not None and track.returncode:
                tail=a.output/'slam/output.log'
                lines=tail.read_text(errors='replace').splitlines()[-8:] if tail.is_file() else []
                detail=next((s.strip() for s in reversed(lines) if 'what():' in s or 'FpgaORB:' in s),lines[-1] if lines else '')
                raise RuntimeError('FPGA/SLAM processing stopped (exit %s): %s'%(track.returncode,detail))
            if server.state=='INITIALIZING' and (a.output/'slam/telemetry/latest.orbv').exists():
                server.state='RUNNING';save(a.output/'session.json',dict(state='RUNNING',port=a.port,process_id=track.pid))
            if (a.output/'stop').exists():
                if track.poll() is None:os.killpg(track.pid,signal.SIGTERM)
                server.state='CANCELLED';break
            paths=[f for f in (a.output/'keyframes_live').glob('*.json') if f.name not in processor.seen]
            if paths:
                paths.sort(key=lambda f:json.loads(f.read_text())['timestamp_ns'])
                processor.process(paths[0]);continue
            if track.poll() is not None:break
            time.sleep(.02)
        code=track.wait(timeout=20)
        processor.close(allow_empty=server.state=='CANCELLED');log.close()
        if server.state!='CANCELLED':
            result=json.loads((a.output/'slam/status.json').read_text())
            if code or not result.get('integration_pass') or result.get('cpu_orb_calls')!=0:
                raise RuntimeError('Actual FPGA tracking run failed')
            server.state='COMPLETED'
        report=processor.report();status=a.output/'slam/status.json'
        report['tracking_seconds']=json.loads(status.read_text()).get('wall_seconds') if status.is_file() else None
        save(a.output/'live_report.json',report);save(a.output/'session.json',dict(state=server.state,port=a.port))
        print('LIVE_SESSION',json.dumps(report),flush=True)
        while a.linger and not (a.output/'stop').exists():time.sleep(.2)
        if not a.linger:time.sleep(2)
    except Exception as exc:
        failure=str(exc);server.state='ERROR';server.error=failure
        save(a.output/'session.json',dict(state='ERROR',error=failure,port=a.port))
        print('LIVE_ERROR',failure,flush=True)
    finally:
        if track is not None and track.poll() is None:os.killpg(track.pid,signal.SIGTERM);track.wait(timeout=20)
        if processor is not None and processor.worker.poll() is None:processor.worker.terminate();processor.worker.wait(timeout=10)
        if log is not None and not log.closed:log.close()
        if failure:
            while a.linger and not (a.output/'stop').exists():time.sleep(.1)
        server.close()
        save(a.output/'done.json',dict(state=server.state,error=failure))
    if failure:raise RuntimeError(failure)


if __name__=='__main__':main()
