"""Bounded PS pipeline protocol gate using compiled C replay backend."""
import argparse
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from client import request_header, receive, decode, HEADER


def main():
    p=argparse.ArgumentParser();p.add_argument('--server',required=True);a=p.parse_args()
    pixels=bytes((i*19+i//960)%256 for i in range(691200))
    with tempfile.TemporaryDirectory() as tmp:
        fixture=Path(tmp)/'replay.bin';payload=bytearray(128+64000+1024)
        budgets=(217,181,151,126,105,87,73,60);offset=0
        for level,count in enumerate(budgets):
            struct.pack_into('<I',payload,level*4,count);struct.pack_into('<I',payload,32+level*4,offset)
            for i in range(count):struct.pack_into('<5I2iI',payload,128+64*(offset+i),100,80,200,level,31,-7,3,31*737280)
            offset+=count
        fixture.write_bytes(payload)
        for case in ('burst','crc','duplicate','timestamp','shape','truncated','disconnect'):
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            proc=subprocess.Popen([a.server,'--replay',str(fixture),'--pipeline','--profile','--once',
                                   '--bind','127.0.0.1','--port',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                assert 'READY' in proc.stdout.readline()
                with socket.create_connection(('127.0.0.1',port),5) as s:
                    s.settimeout(5)
                    if case=='burst':s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,32768)
                    def send(i,header=None,body=pixels):
                        h=header or request_header(i,1000+i,0,pixels)
                        for part in (h[:1],h[1:19],h[19:],body[:3],body[3:]):
                            if part:s.sendall(part)
                    def result(i):
                        h=receive(s,64);f=HEADER.unpack(h);b=receive(s,f[-4])
                        assert f[4]==i and zlib.crc32(b)==f[-2]
                        return h,b,f
                    if case=='burst':
                        errors=[]
                        def producer():
                            try:
                                for i in range(1,65):send(i)
                                s.shutdown(socket.SHUT_WR)
                            except Exception as exc:errors.append(exc)
                        t=threading.Thread(target=producer);t.start();time.sleep(.2)
                        for i in range(1,65):
                            h,b,f=result(i);assert decode(h,b,i,1000+i,0,True)['records']==payload[128:64128]
                        t.join(5);assert not t.is_alive() and not errors
                    elif case=='disconnect':send(1);s.shutdown(socket.SHUT_RDWR)
                    else:
                        send(1)
                        h=bytearray(request_header(2,1002,0,pixels));body=pixels
                        if case=='crc':h[56]^=1
                        if case=='duplicate':struct.pack_into('<Q',h,16,1);body=b''
                        if case=='timestamp':struct.pack_into('<Q',h,24,1001);body=b''
                        if case=='shape':struct.pack_into('<I',h,32,961);body=b''
                        if case=='truncated':body=pixels[:17001]
                        send(2,h,body);s.shutdown(socket.SHUT_WR)
                        h1,b1,f1=result(1);assert f1[-3]==0
                        if case!='truncated':
                            h2,b2,f2=result(1 if case=='duplicate' else 2);assert f2[-3]!=0
                        else:assert s.recv(1)==b''
                out,err=proc.communicate(timeout=8);assert proc.returncode==0,(case,out,err)
                summary=json.loads(next(x.split(' ',1)[1] for x in out.splitlines() if x.startswith('PIPELINE_SUMMARY ')))
                assert summary['ready_high']<=3 and summary['result_high']<=3 and not summary['fatal']
                if case=='burst':
                    assert summary['received']==summary['processed']==summary['sent']==64
                    assert summary['ready_high']>=2 and summary['result_high']>=2,'backpressure not exercised'
                print(case,'PASS',summary)
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
    print('PIPELINE_ORDER_POOL_CRC_BACKPRESSURE_EOF_DISCONNECT_PASS')


if __name__=='__main__':main()
