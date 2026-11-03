"""KV260-local explicitly selected depth backend, RGB fusion and GPU stream."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import os
import select
import cv2
import numpy as np
from .frame_store import FrameStore
from .dense_fusion import Fusion,save
from orb60.dense.live_server import DeltaServer
from orb60.dense.kv260.common import preprocess,write_tensor,read_tensor,digest,INPUT_SHAPE
from orb60.demo_bridge.calibration import read as read_camera


class DpuDepth:
    def __init__(self,config,folder):
        deferred=config.get('defer_worker_until_first_keyframe',False)
        if deferred and (config.get('input_kind')!='live_camera' or not config.get('allow_uninitialized_camera_completion')):
            raise ValueError('Deferred DPU worker requires explicit live-camera no-map handling')
        self.folder=Path(folder);self.inputs=self.folder/'inputs';self.outputs=self.folder/'depth'
        self.inputs.mkdir();self.outputs.mkdir();self.log=(self.folder/'depth_worker.log').open('w')
        required=('model','preflight','placement')
        if any(not Path(config[k]).is_file() for k in required):raise ValueError('Actual DPU model, matching placement and successful board preflight required')
        selection=json.loads(Path(config['selection']).read_text(encoding='utf-8'))
        if not selection.get('user_visual_acceptance') or selection.get('target_model_sha256')!=digest(config['model']):raise ValueError('Depth model differs from the selected QAT model')
        self.command=[sys.executable,'-m','orb60.dense.kv260.worker',config['model'],str(self.inputs),'-',str(self.outputs),
                      '--backend','dpu','--family','midas','--preflight',config['preflight'],'--placement',config['placement']]
        self.worker=None
        if not deferred:self._start()
        self.pending=b'';self.timeout=float(config.get('timeout_seconds',180))

    def _start(self):
        self.worker=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,bufsize=0)

    def infer(self,name,bgr):
        if self.worker is None:self._start()
        write_tensor(self.inputs/(name+'.input.f32'),preprocess(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)),INPUT_SHAPE)
        self.worker.stdin.write((name+'\n').encode());self.worker.stdin.flush();deadline=time.monotonic()+self.timeout
        while True:
            if b'\n' not in self.pending:
                remaining=deadline-time.monotonic()
                if remaining<=0 or not select.select([self.worker.stdout],[],[],remaining)[0]:raise TimeoutError('DPU inference worker timed out')
                data=os.read(self.worker.stdout.fileno(),65536)
                if not data:raise RuntimeError('DPU worker stopped; see depth_worker.log')
                self.pending+=data
                if len(self.pending)>1024*1024:raise RuntimeError('Unbounded worker output')
                continue
            raw,self.pending=self.pending.split(b'\n',1);line=raw.decode(errors='replace')
            self.log.write(line+'\n');self.log.flush()
            if line.startswith('DEPTH_FRAME '+name+' '):break
        return read_tensor(self.outputs/(name+'.output.f32'),(256,256))

    def close(self):
        if self.worker is None:self.log.close();return
        if self.worker.poll() is None:
            self.worker.stdin.close()
            try:code=self.worker.wait(timeout=30)
            except subprocess.TimeoutExpired:self.worker.terminate();code=self.worker.wait(timeout=5)
        else:code=self.worker.returncode
        self.log.close()
        if code:raise RuntimeError('DPU worker failed: '+str(code))


def run(config,run_root,stop_file):
    root=Path(run_root);folder=root/'dense';folder.mkdir(parents=True,exist_ok=True)
    poses=folder/'color_poses';poses.mkdir(exist_ok=True);frames=FrameStore(folder/'rgb_cache')
    camera=read_camera(Path(config['camera']).read_bytes())
    k=np.array([[camera['fx'],0,camera['cx']],[0,camera['fy'],camera['cy']],[0,0,1.]])
    distortion=[camera['d%d'%i] for i in range(5)]
    server=DeltaServer(root,'127.0.0.1',int(config.get('port',18786)),
                       telemetry=Path(config['telemetry_dir']) if config.get('telemetry_dir') else root/'tracking/telemetry',input_kind='kv260_local_rgb')
    backend=config.get('backend','dpu')
    if backend not in ('dpu','ps_cpu'):raise ValueError('Explicit dpu or ps_cpu depth backend required')
    label='kv260_dpu' if backend=='dpu' else 'kv260_ps_cpu'
    voxel_backend=config.get('voxel_backend','reference')
    if voxel_backend not in ('reference','packed'):raise ValueError('Unknown voxel grouping backend')
    from .voxel import PackedVoxelMap,ReferenceVoxelMap
    point_backend=config.get('point_backend','ps')
    if point_backend not in ('ps','pl'):raise ValueError('Explicit ps/pl point projection backend required')
    projector=None;fusion=None;engine=None;seen=set();skipped=[]
    report={'backend':label,'status':'STARTING','hardware_inference_verified':False,
            'keyframes_only':config.get('keyframes_only',False),'voxel_backend':voxel_backend,
            'point_backend':point_backend,'hardware_projection_verified':False,'timings':[]}
    try:
        voxel_class=PackedVoxelMap if voxel_backend=='packed' else ReferenceVoxelMap
        if point_backend=='pl':
            from .point_pl.runtime import Projector
            from .point_pl.fusion import PlFusion
            projector=Projector(config['point_uio'],config['point_abi'],config['point_preflight'],memory_backend=config['point_memory_backend'])
            fusion=PlFusion(folder/'blocks',server.publish,label,projector=projector,voxel_class=voxel_class)
        else:fusion=Fusion(folder/'blocks',server.publish,label,voxel_class=voxel_class)
        if backend=='ps_cpu':
            from .cpu_depth import CpuDepth
            engine=CpuDepth(config,folder)
            if config.get('nice') is not None:os.nice(int(config['nice']))
        else:engine=DpuDepth(config,folder)
        server.state='RUNNING'
        while True:
            if backend=='dpu' and engine.worker is not None and engine.worker.poll() is not None:raise RuntimeError('DPU worker exited before input; see depth_worker.log')
            paths=[p for p in sorted(poses.glob('f*.json'),key=lambda p:int(p.stem[1:])) if p.name not in seen]
            # Tracking never waits for depth. Keep at most two pending anchors;
            # retain the first for parallax and the newest for current geometry.
            if backend=='ps_cpu' and len(paths)>2:
                for old in paths[1:-1]:
                    seen.add(old.name);skipped.append({'frame':int(old.stem[1:]),'reason':'bounded depth queue superseded by newer keyframe'})
                paths=[paths[0],paths[-1]]
            progress=False
            for path in paths:
                if path.name in seen:continue
                meta=json.loads(path.read_text(encoding='utf-8'));name='m%d_f%d'%(meta['map_id'],meta['source_frame_id'])
                if config.get('keyframes_only') and meta.get('anchor_kind')!='slam_keyframe':raise ValueError('Depth requires an actual SLAM keyframe')
                try:bgr=frames.read(meta)
                except FileNotFoundError:
                    if Path(stop_file).exists():raise ValueError('Selected depth keyframe is missing its exact RGB frame after drain')
                    cached=[int(p.stem[1:]) for p in frames.folder.glob('f*.json')]
                    if cached and meta['source_frame_id']<min(cached):
                        seen.add(path.name);skipped.append({'frame':meta['source_frame_id'],'reason':'RGB cache expired before depth processing'})
                    continue
                # Geometry rectifies RGB once. Inference uses that same rectified
                # view, not another frame or a separately resized camera capture.
                mx,my=cv2.initUndistortRectifyMap(k,np.array(distortion),None,k,(960,720),cv2.CV_32FC1)
                rectified=cv2.remap(bgr,mx,my,cv2.INTER_LINEAR)
                start=time.monotonic();prediction=engine.infer(name,rectified)
                inferred=time.monotonic();report['hardware_inference_verified']=backend=='dpu'
                try:fusion.process(meta,bgr,prediction,k,distortion)
                except ValueError as error:skipped.append({'frame':meta['source_frame_id'],'reason':str(error)})
                report['timings'].append({'source_frame_id':meta['source_frame_id'],'keyframe_id':meta['keyframe_id'],
                                          'inference_seconds':inferred-start,'fusion_seconds':time.monotonic()-inferred})
                print('KV260_DENSE_FRAME',name,'backend='+label,'blocks='+str(len(fusion.blocks)),flush=True)
                seen.add(path.name);progress=True
                report.update(status='RUNNING',depth_frames=len(seen),blocks=len(fusion.blocks),skipped=skipped)
                if point_backend=='pl':
                    report.update(hardware_projection_verified=bool(fusion.projection_timings),
                                  projection_timings=fusion.projection_timings,publish_timings=fusion.publish_timings,
                                  point_memory_backend=config['point_memory_backend'],point_reference_check=projector.reference_check)
                save(folder/'status.json',report)
                if backend=='dpu':
                    for old in engine.inputs.glob('*.input.f32'):old.unlink()
                    for old in engine.outputs.glob('*.output.f32'):old.unlink()
            if Path(stop_file).exists() and not [p for p in poses.glob('f*.json') if p.name not in seen]:break
            if not progress:time.sleep(.05)
        from .camera_completion import uninitialized_camera
        if uninitialized_camera(config,root,seen,fusion.blocks):
            engine.close();engine=None
            report.update(status='COMPLETED_NO_MAP_INITIALIZED',maps=[],depth_frames=0,blocks=0,
                          hardware_inference_verified=False,hardware_projection_verified=False,
                          mapping_verified=False,completed_monotonic_ns=time.monotonic_ns(),
                          scope='Actual camera input drained without a map; no DPU inference or colored geometry claimed')
            server.state='COMPLETED';save(folder/'status.json',report)
            if config.get('linger_after_complete'):
                while not (root/'stop_display').exists():time.sleep(.1)
            return report
        final=fusion.finalize(root/'tracking')
        exports=[fusion.export(final['map_id'],folder/('map_%d_dense.ply'%final['map_id']))]
        engine.close();engine=None
        report.update(status='COMPLETED',maps=exports,final_pose_update=final,completed_monotonic_ns=time.monotonic_ns());server.state='COMPLETED';save(folder/'status.json',report)
        if config.get('linger_after_complete'):
            while not (root/'stop_display').exists():time.sleep(.1)
    except Exception as error:
        report.update(status='FAILED',error=repr(error));server.state='ERROR';server.error=str(error);raise
    finally:
        try:
            if engine:engine.close()
        finally:
            try:
                if projector:projector.close()
            finally:save(folder/'status.json',report);server.close()
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--run',type=Path,required=True);p.add_argument('--stop-file',type=Path,required=True)
    a=p.parse_args();run(json.loads(a.config.read_text(encoding='utf-8')),a.run,a.stop_file)
