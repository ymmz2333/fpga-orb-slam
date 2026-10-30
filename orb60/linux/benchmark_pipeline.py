"""Physical-board bounded-window throughput/latency and full-record golden gate.

Run on RK3588 eth0. Simulation flags are always rejected. The three changing
inputs alternate ordinary280, pressure942 and zero-feature images.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import socket
import statistics
import threading
import time
from client import request_header, receive, decode, HEADER


def distribution(values):
    values=sorted(values)
    return dict(mean=statistics.mean(values),p99=values[math.ceil(.99*len(values))-1],max=max(values),min=min(values))


def main():
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--port',type=int,default=5600)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--descriptors',type=Path,required=True)
    p.add_argument('--frames',type=int,default=180);p.add_argument('--window',type=int,choices=(1,2,3),default=3)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert a.frames>=3;a.output.mkdir(parents=True,exist_ok=False)
    info=json.loads((a.descriptors/'vectors.json').read_text());expected=[]
    pixels=[(a.images/f'f{f}_l0_input.bin').read_bytes() for f in range(3)]
    for f in range(3):
        records=bytearray()
        for l in range(8):
            case=info['cases'][f*8+l];name=case['name']+'_features.bin';data=(a.descriptors/name).read_bytes()
            assert hashlib.sha256(data).hexdigest()==info['sha256'][name]
            records.extend(data[case['offset']*64:(case['offset']+case['completed'])*64])
        expected.append(bytes(records))
    sock=socket.create_connection((a.host,a.port),10);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    credit=threading.Semaphore(a.window);stopping=threading.Event();lock=threading.Lock()
    submitted={};errors=[];inflight=0;high=0;samples=[]
    def producer():
        nonlocal inflight,high
        try:
            for i in range(a.frames):
                credit.acquire()
                if stopping.is_set():return
                h=request_header(i+1,1000000000+33333333*i,0,pixels[i%3])
                start=time.monotonic_ns()
                with lock:submitted[i]=start;inflight+=1;high=max(high,inflight)
                sock.sendall(h);sock.sendall(pixels[i%3])
            sock.shutdown(socket.SHUT_WR)
        except Exception as exc:
            errors.append(repr(exc));stopping.set();sock.shutdown(socket.SHUT_RDWR)
    thread=threading.Thread(target=producer);thread.start()
    try:
        for i in range(a.frames):
            header=receive(sock,64);n=HEADER.unpack(header)[-4];assert n<=65152
            payload=receive(sock,n);completed=time.monotonic_ns()
            decoded=decode(header,payload,i+1,1000000000+33333333*i,0)
            assert decoded['records']==expected[i%3],f'full-record mismatch at frame{i}'
            with lock:start=submitted.pop(i);inflight-=1
            if i==0:first_start=start
            samples.append(dict(frame=i+1,input=i%3,count=decoded['count'],latency_ms=(completed-start)/1e6,
                                engine_ms=decoded['engine_ns']/1e6,copy_ms=decoded['input_copy_ns']/1e6,
                                records_sha256=hashlib.sha256(decoded['records']).hexdigest()))
            credit.release()
        thread.join(10);assert not thread.is_alive() and not errors and not submitted and not inflight
        seconds=(completed-first_start)/1e9
        result=dict(status='PASS',scope='physical150MHz PL; no simulated results accepted',frames=a.frames,
                    window=a.window,max_inflight=high,seconds=seconds,fps=a.frames/seconds,all_records_exact=True,
                    latency_ms=distribution([s['latency_ms'] for s in samples]),
                    engine_ms=distribution([s['engine_ms'] for s in samples]),
                    copy_ms=distribution([s['copy_ms'] for s in samples]),samples=samples)
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='samples'},indent=2),flush=True)
    finally:
        stopping.set()
        for _ in range(3):credit.release()
        try:sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        thread.join(10);sock.close()


if __name__=='__main__':main()
