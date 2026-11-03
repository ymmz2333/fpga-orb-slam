"""Bounded byte-only source diagnostic; no pixels, ORB or system FPS claim."""
import argparse,json,socket,struct,time
from pathlib import Path
from .packed_stream import endpoint

HEADER=struct.Struct('<8sQ')


def exact(sock,n):
    data=bytearray()
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part:raise ValueError('Truncated byte benchmark control')
        data.extend(part)
    return data


def run(mode,address,output,buffer_bytes=0,total_bytes=268435456):
    if buffer_bytes not in (0,4194304) or total_bytes!=268435456:raise ValueError('Bounded reviewed transport sizes required')
    output=Path(output)
    if output.exists():raise ValueError('Fresh diagnostic result required')
    host,port=endpoint(address);state=dict(status='RUNNING',mode=mode,buffer_requested=buffer_bytes,bytes=total_bytes,
        scope='Byte-count transport diagnostic only; no frame identity, image processing, hardware or system FPS acceptance')
    sock=None;listener=None
    try:
        if mode=='receive':
            family=socket.AF_INET6 if ':' in host else socket.AF_INET;listener=socket.socket(family,socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            if buffer_bytes:listener.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,buffer_bytes)
            resolved=socket.getaddrinfo(host,port,family,socket.SOCK_STREAM,0,socket.AI_NUMERICHOST|socket.AI_NUMERICSERV)[0][4]
            listener.bind(resolved);listener.listen(1);listener.settimeout(60);sock,_=listener.accept();sock.settimeout(30)
            magic,total=HEADER.unpack(exact(sock,HEADER.size))
            if magic!=b'ORBTOOL1' or total!=total_bytes:raise ValueError('Byte source declaration differs')
            state['actual_socket_buffer']=sock.getsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF);began=time.monotonic();received=0
            while received<total:
                data=sock.recv(min(1048576,total-received))
                if not data:raise ValueError('Byte source ended early')
                received+=len(data)
            state.update(status='BYTE_COUNT_TRANSPORT_DRAINED',seconds=time.monotonic()-began)
            sock.sendall((json.dumps(state)+'\n').encode())
        elif mode=='send':
            sock=socket.create_connection((host,port),timeout=5);sock.settimeout(30)
            if buffer_bytes:sock.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,buffer_bytes)
            sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);state['actual_socket_buffer']=sock.getsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF)
            block=bytes(960*720*2+32);sock.sendall(HEADER.pack(b'ORBTOOL1',total_bytes));sent=0;began=time.monotonic()
            while sent<total_bytes:
                n=min(len(block),total_bytes-sent);sock.sendall(block if n==len(block) else block[:n]);sent+=n
            state.update(status='BYTE_COUNT_TRANSPORT_SENT',seconds=time.monotonic()-began)
            ack=bytearray()
            while not ack.endswith(b'\n'):
                if len(ack)>4096:raise ValueError('Unexpected byte benchmark acknowledgment')
                part=sock.recv(4096)
                if not part:raise ValueError('Missing receiver acknowledgment')
                ack.extend(part)
            state['receiver']=json.loads(ack)
            if state['receiver']['bytes']!=total_bytes or state['receiver']['status']!='BYTE_COUNT_TRANSPORT_DRAINED':raise ValueError('Byte count not acknowledged')
        else:raise ValueError('Explicit send or receive mode required')
        state['MB_per_second']=total_bytes/state['seconds']/1e6
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        if sock:sock.close()
        if listener:listener.close()
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['send','receive']);p.add_argument('--address',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--buffer-bytes',type=int,default=0)
    run(**vars(p.parse_args()))
