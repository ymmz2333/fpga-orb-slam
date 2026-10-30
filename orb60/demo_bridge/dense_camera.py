"""Exact-frame low-rate camera color -> existing NPU -> incremental RGB blocks."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import socket
import select
import threading
import time
from types import SimpleNamespace
import zlib

import cv2
import numpy as np
from .calibration import read, fingerprint
from .protocol import Packet, Kind, PROFILE, connect, receive
from orb60.dense.live_server import DeltaServer
from orb60.dense.geometry import camera_points, VoxelMap
POINT=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))])


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def save(path,value):
    path=Path(path);part=path.with_suffix('.part')
    part.write_text(json.dumps(value,indent=2)+'\n');part.replace(path)


class GroupedChunks:
    """Fuse eight successive samples locally; upload only that bounded point block."""
    def __init__(self,server,folder):
        self.server=server;self.folder=Path(folder);self.current={};self.blocks={}

    def publish(self,meta,payload):
        meta=dict(meta);anchor_observations=meta.pop('_anchor_observations',None)
        mid=int(meta['map_id']);block=self.current.get(mid)
        if block is None or block['samples']>=8:
            if len(self.blocks)>=128:raise ValueError('Dense preview capacity reached; preserve completed local blocks')
            base=dict(meta);base['source_frame_range']=[meta['source_frame_index'],meta['source_frame_index']]
            block=dict(meta=base,pose=np.asarray(meta['twc']),voxel=VoxelMap(meta['voxel_edge'],capacity=12000),samples=0,anchor_observations=anchor_observations)
            self.current[mid]=block;self.blocks[mid,meta['keyframe_id']]=block
        points=np.frombuffer(payload,dtype=POINT);pose=np.asarray(meta['twc'])
        world=points['xyz']@pose[:3,:3].T+pose[:3,3]
        block['voxel'].add(camera_points(world,block['pose']),points['rgb'])
        xyz,rgb=block['voxel'].arrays();out=np.empty(len(xyz),dtype=POINT);out['xyz']=xyz;out['rgb']=rgb
        block['samples']+=1;base=block['meta'];base.update(points=len(out),revision=block['samples'],
            voxel_edge=block['voxel'].edge,coordinates='sample_group_anchor_camera_local')
        base['source_frame_range'][1]=meta['source_frame_index']
        self.server.publish(dict(base),out.tobytes())
        name='m%d_g%d'%(mid,-int(base['keyframe_id']))
        if block['samples']==1 and block['anchor_observations'] is not None:
            anchors=self.folder.parent/'anchors';anchors.mkdir(exist_ok=True)
            save(anchors/(name+'.json'),dict(observations=block['anchor_observations'],twc=base['twc'],source_frame_index=base['source_frame_index']))
        (self.folder/(name+'.bin')).write_bytes(out.tobytes());save(self.folder/(name+'.json'),base)

    @property
    def state(self):return self.server.state

    def counts(self):
        return len(self.blocks),sum(len(b['voxel'].counts) for b in self.blocks.values())


def decode_color(packet, metadata):
    if (packet.kind != Kind.COLOR or packet.flags or packet.count or
            not 4 <= len(packet.body) <= 4*1024*1024 or
            (packet.session,packet.frame,packet.stamp,packet.aux) !=
            (int(metadata['session']),int(metadata['source_frame_id']),
             int(metadata['timestamp_ns']),int(metadata['gray_crc']))):
        raise ValueError('Color/pose source identity mismatch')
    image=cv2.imdecode(np.frombuffer(packet.body,np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape!=(720,1280,3):
        raise ValueError('Color camera geometry mismatch; expected source MJPEG1280x720')
    # Exact crop, no resize or second undistortion. Geometry later rectifies once.
    return image[:,160:1120].copy()


class ColorReceiver:
    def __init__(self,host,port,calibration):
        self.host,self.port,self.calibration=host,port,calibration
        self.lock=threading.Lock();self.stop=threading.Event();self.frames=OrderedDict()
        self.received=0;self.bytes=0;self.evicted=0;self.error='';self.sock=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        try:
            with connect(self.host,self.port,10) as sock:
                self.sock=sock;sock.sendall(Packet(Kind.HELLO,body=self.calibration.encode()).encode())
                hello=receive(sock)
                expected=self.calibration+'\n'+PROFILE+'\nMJPEG1280x720-CROP160-V1'
                if hello.kind!=Kind.HELLO or hello.count!=1 or hello.body.decode()!=expected:
                    raise ValueError('Color transport calibration/capability mismatch')
                sock.settimeout(10);last=None;last_progress=time.monotonic()
                while not self.stop.is_set():
                    if not select.select([sock],[],[],1)[0]:
                        if time.monotonic()-last_progress>20:raise RuntimeError('No current camera color samples for20s')
                        continue
                    p=receive(sock)
                    if p.kind!=Kind.COLOR or not p.session or not p.stamp or p.flags or p.count or len(p.body)>4*1024*1024:
                        raise ValueError('Invalid color packet')
                    identity=(p.session,p.frame,p.stamp)
                    if last and (p.session!=last[0] or p.frame<=last[1] or p.stamp<=last[2]):
                        raise ValueError('Nonmonotonic/mixed color session')
                    last=identity;last_progress=time.monotonic()
                    with self.lock:
                        self.frames[p.frame]=p;self.received+=1;self.bytes+=len(p.body)
                        while len(self.frames)>32:self.frames.popitem(last=False);self.evicted+=1
        except Exception as exc:
            if not self.stop.is_set():self.error=str(exc)
        finally:self.sock=None

    def take(self,index):
        with self.lock:return self.frames.pop(index,None)

    def close(self):
        self.stop.set()
        if self.sock:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        self.thread.join(timeout=12)


class DenseCamera:
    def __init__(self,config,run):
        from orb60.dense.live import OnlineDepth
        self.config=config;self.run=Path(run);self.root=self.run/'dense'
        self.root.mkdir(exist_ok=True);(self.root/'chunks').mkdir();(self.root/'color_poses').mkdir(exist_ok=True)
        gate=json.loads(Path(config['npu_acceptance']).read_text())
        if gate['status']!='PASS' or gate['model_sha256']!=sha(config['depth_model']):
            raise ValueError('Matching physically verified NPU model required')
        self.camera=read(Path(config['camera']).read_bytes())
        self.k=np.array([[self.camera['fx'],0,self.camera['cx']],[0,self.camera['fy'],self.camera['cy']],[0,0,1.]])
        self.distortion=[self.camera['d%d'%i] for i in range(5)]
        self.receiver=ColorReceiver(config['zynq_host'],config.get('color_port',5604),fingerprint(Path(config['camera']).read_bytes()))
        self.server=DeltaServer(self.run,'0.0.0.0',config.get('dense_port',18786),telemetry=self.run/'telemetry',input_kind='camera_bridge')
        self.server.state='INITIALIZING';self.stop=threading.Event();self.closed=False;self.error=''
        self.grouped=GroupedChunks(self.server,self.root/'chunks')
        self.sources={};self.current_color=None;self.matches=0;self.expired=0
        self.started=time.monotonic();self.proof=(self.root/'pairing.jsonl').open('w')
        args=SimpleNamespace(output=self.root,worker=Path(config['depth_worker']),model=Path(config['depth_model']),video=None,frame_chunks=False,retain_anchor_observations=True)
        self.processor=OnlineDepth(args,self.grouped,self.sources,lambda index:self.current_color)
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()

    def status(self):
        return dict(state=self.server.state,error=self.error,color_frames=self.receiver.received,
                    color_jpeg_bytes=self.receiver.bytes,matched_frames=self.matches,npu_frames=self.processor.npu_frames,
                    points=self.grouped.counts()[1],chunks=self.grouped.counts()[0],
                    expired=self.expired,color_cache_capacity=32,pose_semantics='provisional tracked-frame anchors')

    def loop(self):
        pending={}
        try:
            while not self.stop.is_set():
                if self.receiver.error:raise RuntimeError(self.receiver.error)
                paths=list((self.root/'color_poses').glob('f*.json'))
                paths.sort(key=lambda p:int(p.stem[1:]))
                if not paths:self.stop.wait(.02);continue
                for path in paths:
                    if self.stop.is_set():break
                    meta=json.loads(path.read_text());index=int(meta['source_frame_id'])
                    p=self.receiver.take(index)
                    if p is None:
                        began=pending.setdefault(path.name,time.monotonic())
                        if time.monotonic()-began>5:
                            self.expired+=1;path.unlink();pending.pop(path.name,None)
                        continue
                    self.current_color=decode_color(p,meta)
                    meta['k']=self.k.tolist();meta['distortion']=self.distortion
                    obs=np.asarray(meta['observations'],float);q=camera_points(obs[:,2:5],np.asarray(meta['twc']))
                    uv=q[:,:2]/q[:,2:3]*np.array([self.camera['fx'],self.camera['fy']])+np.array([self.camera['cx'],self.camera['cy']])
                    keep=(q[:,2]>1e-6)&np.isfinite(uv).all(axis=1)&(np.linalg.norm(uv-obs[:,:2],axis=1)<=3)
                    meta['observations']=obs[keep].tolist()
                    save(path,meta)
                    stamp=int(meta['timestamp_ns']);self.sources[stamp]=dict(source_frame_index=index,mp4_pts_s=stamp*1e-9)
                    self.matches+=1;self.server.state='RUNNING'
                    self.proof.write(json.dumps(dict(session=p.session,frame=p.frame,timestamp_ns=p.stamp,
                        gray_crc=p.aux,jpeg_sha256=hashlib.sha256(p.body).hexdigest(),map_id=meta['map_id'],
                        anchor_kind=meta['anchor_kind'],reliable_correspondences=int(keep.sum())))+'\n');self.proof.flush()
                    # The existing OnlineDepth path runs the verified C++ NPU worker,
                    # robust inverse-depth fit and multiview/voxel filtering.
                    self.processor.process(path)
                    self.sources.pop(stamp,None);path.unlink();pending.pop(path.name,None)
                    save(self.root/'status.json',dict(self.status(),processing=self.processor.report()))
                    if self.processor.npu_frames>4:
                        for folder,pattern in ((self.root/'inputs','*.input.f32'),(self.root/'npu','*.output.f32')):
                            for file in folder.glob(pattern):file.unlink()
        except Exception as exc:
            if not self.stop.is_set():
                self.error=str(exc);self.server.state='ERROR';self.server.error=self.error
                save(self.root/'failure.json',dict(error=self.error))

    def close(self):
        if self.closed:return
        self.closed=True;self.stop.set();self.receiver.close();self.thread.join(timeout=20)
        if self.thread.is_alive():
            self.processor.worker.terminate();self.thread.join(timeout=5)
        if self.processor.worker.poll() is None:
            self.processor.close(allow_empty=True)
        self.proof.close();save(self.root/'status.json',dict(self.status(),processing=self.processor.report()))
        self.server.state='CANCELLED';self.server.close()
