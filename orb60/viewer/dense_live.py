"""Live dense deltas: retained per-keyframe GPU buffers and independent camera updates."""
import collections
import os
from pathlib import Path
import socket
import sys
import threading
import time
import numpy as np
from PySide6 import QtGui
if os.getenv('ORB60_VIEWER_RENDERER')=='egl-raster':
    import egl_raster_view as gl
elif os.getenv('ORB60_VIEWER_RENDERER')=='gles':
    import gles_view as gl
elif os.getenv('ORB60_VIEWER_RENDERER')=='desktop':
    import desktop_view as gl
else:
    import pyqtgraph.opengl as gl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dense.live_protocol import receive
from protocol import Snapshot
from model import WORLD_TO_VIEW,view_points

POINT=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))])


def live_point_diameter(edge,total,displayed,multiplier):
    # Sparse display sampling must not turn close-up points into large blobs.
    compensation=min(1.25,np.sqrt(max(1.,total/max(1,displayed))))
    return edge*multiplier*compensation


class DenseLiveSource(threading.Thread):
    def __init__(self,host,port):
        super().__init__(daemon=True);self.host=host;self.port=port
        self.stop=threading.Event();self.lock=threading.Lock();self.latest=None;self.chunks=collections.deque()
        self.sock=None;self.state='CONNECTING';self.error='';self.received=0;self.replaced=0;self.last_arrival=0.
        self.pending_completion=False
        self.session=None;self.generation=0
        self.connected_once=False
        self.input_kind='video'

    def run(self):
        deadline=time.monotonic()+12
        while not self.stop.is_set():
            try:
                self.sock=socket.create_connection((self.host,self.port),5);self.sock.settimeout(5)
                self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                self.state='CONNECTED';self.error=''
                while not self.stop.is_set():
                    meta,data=receive(self.sock)
                    if meta['event']=='hello':
                        self.connected_once=True
                        self.input_kind=meta.get('input_kind','video')
                        with self.lock:
                            if self.session!=meta['session']:
                                self.session=meta['session'];self.generation+=1;self.latest=None;self.chunks.clear()
                                self.pending_completion=False
                    elif meta['event']=='frame':
                        snapshot=Snapshot.decode(data)
                        if snapshot.meta.get('source')!='fpga' or snapshot.meta.get('cpu_orb_calls')!=0:
                            raise ValueError('实时模式拒绝非 FPGA 或 CPU 回退结果')
                        with self.lock:
                            if self.latest is not None:self.replaced+=1
                            self.latest=snapshot;self.received+=1;self.last_arrival=time.perf_counter()
                        self.state='RUNNING'
                    elif meta['event']=='chunk':
                        count=meta['points']
                        if not 0<count<=12000 or len(data)!=count*POINT.itemsize:raise ValueError('Invalid live chunk length')
                        points=np.frombuffer(data,dtype=POINT).copy();pose=np.array(meta['twc'])
                        if pose.shape!=(4,4) or not np.isfinite(pose).all() or not np.isfinite(points['xyz']).all():
                            raise ValueError('Invalid live dense coordinates')
                        while not self.stop.is_set():
                            with self.lock:
                                if len(self.chunks)<128:self.chunks.append((meta,points));break
                            self.stop.wait(.01)
                    elif meta['event']=='status':
                        with self.lock:
                            if meta['state'] in ('ERROR','CANCELLED'):
                                self.error=meta.get('error') or '实际处理已停止'
                                self.latest=None;self.chunks.clear()
                            self.pending_completion=meta['state']=='COMPLETED' and bool(self.chunks)
                            self.state='DRAINING' if self.pending_completion else meta['state']
                        if meta['state'] in ('ERROR','CANCELLED'):return
                    else:raise ValueError('Unknown live dense event')
            except (OSError,ValueError,ConnectionError) as exc:
                self.error=str(exc)
                if self.stop.is_set():return
                if self.connected_once or time.monotonic()>=deadline:
                    if self.state!='COMPLETED':
                        self.state='ERROR';self.error='实时连接中断，处理已停止：'+str(exc)
                        with self.lock:self.latest=None;self.chunks.clear()
                    return
                self.state='CONNECTING'
            finally:
                if self.sock:self.sock.close();self.sock=None
            self.stop.wait(1)

    def take(self):
        with self.lock:value=self.latest;self.latest=None;return value

    def take_chunks(self):
        with self.lock:
            result=[]
            for _ in range(min(2,len(self.chunks))):result.append(self.chunks.popleft())
            if self.pending_completion and not self.chunks:self.state='COMPLETED';self.pending_completion=False
            return result

    def close(self):
        self.stop.set()
        if self.sock:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        self.join(timeout=6)


class LiveChunkLayer:
    """Each upload is one new keyframe. Pose corrections alter a matrix, not point buffers."""
    def __init__(self,map_view):
        self.map_view=map_view;self.chunks={};self.map_id=None;self.visible=True
        self.max_budget=int(os.getenv('ORB60_VIEWER_POINT_BUDGET','200000'))
        self.uploads=0;self.pose_updates=0;self.budget=self.max_budget;self.multiplier=1.0

    def select_map(self,mid):
        self.map_id=mid
        for (map_id,_),chunk in self.chunks.items():chunk['item'].setVisible(self.visible and map_id==mid)

    def set_visible(self,value):self.visible=value;self.select_map(self.map_id)

    def transform(self,chunk,pose):
        pose=np.array(pose,np.float32)
        if np.allclose(pose,chunk.get('pose',np.zeros((4,4))),rtol=0,atol=1e-7):return
        world=np.eye(4,dtype=np.float32);world[:3,:3]=WORLD_TO_VIEW
        matrix=world@pose
        chunk['item'].setTransform(QtGui.QMatrix4x4(*map(float,matrix.ravel())))
        chunk['pose']=pose;self.pose_updates+=1

    def upload(self,chunk,budget):
        points=chunk['points'];count=len(points)
        if count>budget:
            ids=np.sort(np.random.RandomState(1729).choice(count,budget,replace=False))
        else:ids=np.arange(count)
        rgb=points['rgb'][ids].astype(np.float32)/255.
        fixed=float(os.getenv('ORB60_POINT_PIXELS','0'))
        chunk['item'].setData(pos=points['xyz'][ids],color=np.c_[rgb,np.ones(len(ids),np.float32)],
                              size=fixed if fixed else live_point_diameter(chunk['meta']['voxel_edge'],count,len(ids),self.multiplier),pxMode=bool(fixed))
        chunk['displayed']=len(ids);self.uploads+=1

    def add(self,meta,points):
        key=(meta['map_id'],meta['keyframe_id'])
        if key in self.chunks:
            old=self.chunks[key]
            if meta['revision']<=old['meta']['revision']:return
            old['meta']=meta;old['points']=points;self.upload(old,self.budget)
            self.transform(old,meta['twc']);self.update_fit_points();return
        if len(self.chunks)>=128:raise ValueError('Live cloud exceeds bounded chunk capacity')
        item=gl.GLScatterPlotItem(pos=np.empty((0,3)),size=1,pxMode=False,glOptions='opaque')
        self.map_view.view.addItem(item)
        chunk=dict(item=item,meta=meta,points=points);self.chunks[key]=chunk
        # Rebalance only at powers of two, never for ordinary video frames.
        bucket=2**int(np.ceil(np.log2(max(1,len(self.chunks)))))
        budget=max(1,self.max_budget//bucket)
        if budget!=self.budget:
            self.budget=budget
            for current in self.chunks.values():self.upload(current,budget)
        else:self.upload(chunk,budget)
        self.transform(chunk,meta['twc']);self.select_map(self.map_id)
        self.update_fit_points()

    def update_poses(self,keyframes):
        changed=False
        for record in keyframes:
            key=(self.map_id,int(record['id']))
            if key in self.chunks:
                before=self.pose_updates;self.transform(self.chunks[key],record['twc']);changed|=before!=self.pose_updates
        if changed:self.update_fit_points()

    def update_fit_points(self):
        samples=[]
        for (mid,_),chunk in self.chunks.items():
            if mid!=self.map_id:continue
            xyz=chunk['points']['xyz'];ids=np.linspace(0,len(xyz)-1,min(128,len(xyz)),dtype=int)
            samples.append(xyz[ids]@chunk['pose'][:3,:3].T+chunk['pose'][:3,3])
        self.map_view.dense_points=np.concatenate(samples) if samples else np.empty((0,3),np.float32)

    def arrays(self):
        xyz=[];rgb=[]
        for (mid,_),c in self.chunks.items():
            if mid!=self.map_id:continue
            xyz.append(c['points']['xyz']@c['pose'][:3,:3].T+c['pose'][:3,3]);rgb.append(c['points']['rgb'])
        return (np.concatenate(xyz),np.concatenate(rgb)) if xyz else (np.empty((0,3),np.float32),np.empty((0,3),np.uint8))

    def counts(self):
        chunks=[c for (mid,_),c in self.chunks.items() if mid==self.map_id]
        return len(chunks),sum(len(c['points']) for c in chunks),sum(c['displayed'] for c in chunks)

    def close(self):
        for c in self.chunks.values():self.map_view.view.removeItem(c['item'])
        self.chunks.clear()
