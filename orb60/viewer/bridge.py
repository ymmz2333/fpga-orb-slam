"""Read-only TCP bridge, loopback by default. Slow viewers never block SLAM."""
import argparse
import json
from pathlib import Path
import signal
import socket
import threading
import time

# No Qt/numpy dependency is needed on the RK bridge.
import struct
import zlib


def status_packet(state):
    body=json.dumps(dict(event='status',session_state=state)).encode()
    return struct.pack('<8s6I',b'ORBVIZ01',1,len(body),0,0,0,zlib.crc32(body))+body


class Bridge:
    def __init__(self,directory,host,port):
        self.directory=Path(directory);self.stop=threading.Event();self.slots=threading.BoundedSemaphore(3)
        self.socket=socket.socket();self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.socket.bind((host,port));self.socket.listen(3);self.socket.settimeout(.5)

    def client(self,conn):
        try:
            conn.settimeout(2);last=None;heartbeat=0
            while not self.stop.is_set():
                try:
                    node=self.directory/'latest.orbv';stat=node.stat();identity=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
                    if identity!=last:
                        data=node.read_bytes()
                        if len(data)>5*1024*1024:raise ValueError('snapshot exceeds bridge bound')
                        conn.sendall(data);last=identity
                except FileNotFoundError:pass
                if time.monotonic()-heartbeat>=1:
                    try:state=json.loads((self.directory/'status.json').read_text()).get('state','UNKNOWN')
                    except (FileNotFoundError,json.JSONDecodeError):state='WAITING'
                    try:
                        parent=json.loads((self.directory.parent/'status.json').read_text()).get('state')
                        if parent=='FAILED':state='ERROR'
                        elif parent=='COMPLETED':state='COMPLETED'
                    except (FileNotFoundError,json.JSONDecodeError):pass
                    conn.sendall(status_packet(state));heartbeat=time.monotonic()
                self.stop.wait(.005)
        except (OSError,ValueError):pass
        finally:conn.close();self.slots.release()

    def serve(self):
        print('ORB_VIEWER_BRIDGE_READY',self.socket.getsockname(),flush=True)
        try:
            while not self.stop.is_set():
                try:conn,_=self.socket.accept()
                except socket.timeout:continue
                if not self.slots.acquire(blocking=False):conn.close();continue
                threading.Thread(target=self.client,args=(conn,),daemon=True).start()
        finally:self.stop.set();self.socket.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--bind',default='127.0.0.1');p.add_argument('--port',type=int,default=8765)
    p.add_argument('--duration',type=float,default=0,help='Optional bounded integration-test lifetime');a=p.parse_args()
    bridge=Bridge(a.directory,a.bind,a.port)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:bridge.stop.set())
    if a.duration:
        timer=threading.Timer(a.duration,bridge.stop.set);timer.daemon=True;timer.start()
    bridge.serve()


if __name__=='__main__':main()
