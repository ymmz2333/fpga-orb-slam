"""Latest-frame video plus reliable per-keyframe point additions; tracking never waits for viewers."""
import json
from pathlib import Path
import socket
import threading
import time
from .live_protocol import encode


class DeltaServer:
    def __init__(self,root,host,port,telemetry=None,input_kind='video'):
        self.root=Path(root);self.stop=threading.Event();self.lock=threading.Lock()
        self.telemetry=Path(telemetry) if telemetry else self.root/'slam/telemetry'
        self.input_kind=input_kind
        self.chunks={};self.state='STARTING';self.error='';self.slots=threading.BoundedSemaphore(3)
        self.socket=socket.socket();self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.socket.bind((host,port));self.socket.listen(3);self.socket.settimeout(.5)
        self.thread=threading.Thread(target=self.serve,daemon=True);self.thread.start()

    def publish(self,meta,payload):
        key=(meta['map_id'],meta['keyframe_id'])
        with self.lock:
            if len(self.chunks)>=128 and key not in self.chunks:raise ValueError('Live preview chunk capacity reached')
            self.chunks[key]=(meta['revision'],encode(meta,payload))

    def client(self,conn):
        try:
            conn.settimeout(3);sent={};last_frame=None;heartbeat=0
            conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            conn.sendall(encode(dict(event='hello',session=self.root.name,input_kind=self.input_kind)))
            while not self.stop.is_set():
                path=self.telemetry/'latest.orbv'
                try:
                    stat=path.stat();identity=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
                    if identity!=last_frame and self.state not in ('ERROR','CANCELLED','CHECKING_FPGA'):
                        frame=path.read_bytes();conn.sendall(encode(dict(event='frame'),frame));last_frame=identity
                except FileNotFoundError:pass
                with self.lock:new=next(((key,value) for key,value in self.chunks.items() if sent.get(key)!=value[0]),None)
                if new and self.state not in ('ERROR','CANCELLED'):
                    key,(revision,data)=new;conn.sendall(data);sent[key]=revision
                if time.monotonic()-heartbeat>1:
                    state='DRAINING' if self.state=='COMPLETED' and len(sent)<len(self.chunks) else self.state
                    conn.sendall(encode(dict(event='status',state=state,chunks=len(self.chunks),
                                            error=self.error,semantics='actual incremental processing; provisional online map')))
                    heartbeat=time.monotonic()
                self.stop.wait(.005)
        except (OSError,ValueError):pass
        finally:conn.close();self.slots.release()

    def serve(self):
        while not self.stop.is_set():
            try:conn,_=self.socket.accept()
            except socket.timeout:continue
            except OSError:break
            if not self.slots.acquire(blocking=False):conn.close();continue
            threading.Thread(target=self.client,args=(conn,),daemon=True).start()

    def close(self):
        self.stop.set();self.socket.close();self.thread.join(timeout=3)
