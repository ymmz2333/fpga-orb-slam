"""Bounded hardware fault injection: forward one probe, then cut the real stream."""
import argparse,json,select,socket,time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=15600)
p.add_argument('--host',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
host,port=a.host[1:].split(']:',1) if a.host.startswith('[') else a.host.rsplit(':',1)
listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
listener.bind(('127.0.0.1',a.port));listener.listen(1);listener.settimeout(90)
print('FAULT_PROXY_READY',flush=True)
try:
    for number in (1,2):
        client,_=listener.accept();upstream=socket.create_connection((host,int(port)),5)
        peers={client:upstream,upstream:client};received=0;cut=False
        try:
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                ready,_,_=select.select(list(peers),[],[],1)
                disconnected=False
                for source in ready:
                    data=source.recv(65536)
                    if not data:disconnected=True;break
                    if source is upstream:received+=len(data)
                    peers[source].sendall(data)
                    if number==2 and received>130000:cut=True;break
                if cut or disconnected:break
        finally:client.close();upstream.close()
        if number==2:
            if not cut:raise RuntimeError('No real hardware stream was interrupted')
            a.output.write_text(json.dumps(dict(status='INJECTED',connections=number,hardware_reply_bytes=received)))
            print('FAULT_PROXY_CUT',received,flush=True)
finally:listener.close()
