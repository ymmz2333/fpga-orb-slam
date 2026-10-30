"""Network input uses one replaceable slot or bounded paced playout, never an unbounded Qt queue."""
import json
from pathlib import Path
import socket
import threading
import time
from collections import deque
from protocol import Snapshot,receive_snapshot


class PlayoutQueue:
    """Bounded timestamp playout for paced inputs; trades a little latency for smoothness."""
    def __init__(self,delay_ms,capacity=8):
        self.delay=delay_ms/1000;self.capacity=capacity;self.frames=deque();self.origin=None;self.dropped=0

    def push(self,snapshot,now):
        stamp=snapshot.meta['timestamp_ns']/1e9
        if self.origin is None:self.origin=(stamp,now)
        if len(self.frames)==self.capacity:self.frames.popleft();self.dropped+=1
        self.frames.append(snapshot)

    def take(self,now):
        if not self.frames:return None
        due=self.origin[1]+self.delay+self.frames[0].meta['timestamp_ns']/1e9-self.origin[0]
        return self.frames.popleft() if now>=due else None


class LiveSource(threading.Thread):
    def __init__(self,host,port,buffer_ms=0):
        super().__init__(daemon=True);self.host=host;self.port=port;self.stop=threading.Event();self.lock=threading.Lock()
        self.latest=None;self.last_arrival=0.;self.state='CONNECTING';self.error='';self.sock=None;self.replaced=0;self.received=0
        self.playout=PlayoutQueue(buffer_ms) if buffer_ms else None

    def run(self):
        while not self.stop.is_set():
            try:
                self.sock=socket.create_connection((self.host,self.port),3);self.sock.settimeout(3)
                self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                self.state='CONNECTED';self.error=''
                while not self.stop.is_set():
                    snapshot=receive_snapshot(self.sock)
                    if snapshot.meta.get('event')=='status':self.state=snapshot.meta.get('session_state','UNKNOWN');continue
                    with self.lock:
                        self.received+=1
                        self.last_arrival=time.perf_counter()
                        if self.playout:
                            self.playout.push(snapshot,self.last_arrival);self.replaced=self.playout.dropped
                        else:
                            if self.latest is not None:self.replaced+=1
                            self.latest=snapshot
            except (OSError,ValueError,ConnectionError) as exc:
                self.error=str(exc);self.state='DISCONNECTED'
            finally:
                if self.sock:
                    try:self.sock.close()
                    except OSError:pass
                self.sock=None
            self.stop.wait(1)

    def take(self):
        with self.lock:
            if self.playout:return self.playout.take(time.perf_counter())
            value=self.latest;self.latest=None;return value

    def close(self):
        self.stop.set()
        if self.sock:
            try:self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        self.join(timeout=4)


class Recording:
    def __init__(self,directory):
        directory=Path(directory);self.directory=directory
        self.paths=sorted((directory/'frames').glob('*.orbv')) if (directory/'frames').is_dir() else sorted(directory.glob('*.orbv'))
        if not self.paths:raise ValueError('此目录没有 .orbv 可视化记录')
        self.timeline=[]
        for path in self.paths:
            snap=Snapshot.decode(path.read_bytes());m=snap.meta
            self.timeline.append({k:m[k] for k in ('frame_index','timestamp_ns','map_id','pose_twc','pose_valid','state','map_full')})
        if any(a['frame_index']>=b['frame_index'] for a,b in zip(self.timeline,self.timeline[1:])):
            raise ValueError('记录帧号不递增')

    def read(self,index):return Snapshot.decode(self.paths[index].read_bytes())

    def nearest_map(self,index):
        map_id=self.timeline[index]['map_id']
        while index>=0 and self.timeline[index]['map_id']==map_id:
            if self.timeline[index]['map_full']:return self.read(index)
            index-=1
        return None


class ColorVideo(threading.Thread):
    """Optional original MP4 by exact decoded frame index; decoding stays off the GUI."""
    def __init__(self,path,transform=None,fast_seek=False,exact_gray=False):
        super().__init__(daemon=True);self.path=str(path);self.stop=threading.Event();self.changed=threading.Event()
        self.lock=threading.Lock();self.request=None;self.result=None;self.error=''
        self.transform=transform
        self.fast_seek=fast_seek
        self.exact_gray=exact_gray

    def take_crc(self,token):
        with self.lock:
            return self.result[2] if self.result and self.result[0]==token and len(self.result)>2 else None

    def run_exact(self):
        import av
        import zlib
        container=None;next_index=0
        try:
            container=av.open(self.path);frames=iter(container.decode(video=0))
            while not self.stop.is_set():
                self.changed.wait(.2);self.changed.clear()
                with self.lock:request=self.request;self.request=None
                if request is None:continue
                index,token=request
                with self.lock:
                    if self.result and self.result[0]==token:continue
                if index<next_index:
                    container.close();container=av.open(self.path);frames=iter(container.decode(video=0));next_index=0
                frame=None
                while next_index<=index and not self.stop.is_set():
                    frame=next(frames);next_index+=1
                if self.stop.is_set():return
                image=frame.to_ndarray(format='bgr24');gray=frame.to_ndarray(format='gray')
                if image.shape[:2]!=(720,960):raise ValueError('原片尺寸与 FPGA 输入不符')
                with self.lock:self.result=(token,image,zlib.crc32(gray.tobytes()))
        except Exception as exc:self.error='精确源帧解码失败：'+str(exc)
        finally:
            if container is not None:container.close()

    def ask(self,index,token=None):
        token=index if token is None else token
        with self.lock:
            if self.result and self.result[0]==token:return
            self.request=(index,token)
        self.changed.set()

    def take(self,index):
        with self.lock:
            if self.result and self.result[0]==index:return self.result[1]
        return None

    def run(self):
        if self.exact_gray:
            self.run_exact();return
        import cv2
        cap=cv2.VideoCapture(self.path);next_index=0
        if self.transform is not None:cap.set(getattr(cv2,'CAP_PROP_ORIENTATION_AUTO',49),0)
        if not cap.isOpened():self.error='无法解码彩色原片';return
        try:
            while not self.stop.is_set():
                self.changed.wait(.3);self.changed.clear()
                with self.lock:request=self.request;self.request=None
                if request is None:continue
                index,token=request
                with self.lock:
                    if self.result and self.result[0]==token:continue
                # Forward decode preserves H.264 reference pictures. Repeated random
                # seeks can produce damaged previews even for a valid source recording.
                # Dense offline replay uses a FRESH decoder for long/backward seeks;
                # sequential playback and the existing live source remain unchanged.
                if self.fast_seek and (index<next_index or index-next_index>90):
                    cap.release();cap=cv2.VideoCapture(self.path)
                    if self.transform is not None:cap.set(getattr(cv2,'CAP_PROP_ORIENTATION_AUTO',49),0)
                    if not cap.set(cv2.CAP_PROP_POS_FRAMES,index) or abs(cap.get(cv2.CAP_PROP_POS_FRAMES)-index)>.1:
                        raise ValueError('视频解码器无法准确定位到请求帧')
                    next_index=index
                elif index<next_index:
                    cap.release();cap=cv2.VideoCapture(self.path);next_index=0
                    if self.transform is not None:cap.set(getattr(cv2,'CAP_PROP_ORIENTATION_AUTO',49),0)
                while next_index<index and not self.stop.is_set():
                    if not cap.grab():break
                    next_index+=1
                if self.stop.is_set():break
                if next_index!=index:self.error=f'原片没有第{index}帧';continue
                ok,image=cap.read();next_index=index+1
                if not ok:self.error=f'原片没有第{index}帧';continue
                if self.transform is not None:image=self.transform(image)
                if image.shape[:2]!=(720,960):self.error='原片分辨率应为960×720';continue
                self.error=''
                with self.lock:self.result=(token,image)
        except Exception as exc:self.error='原片回放失败：'+str(exc)
        finally:cap.release()

    def close(self):self.stop.set();self.changed.set();self.join(timeout=3)
