"""Loopback-only wire model for the real C++ adapter; no board performance claim."""
import argparse
import csv
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import threading
import time
import zlib
from client import HEADER, receive, WIDTHS, HEIGHTS


def main():
    p=argparse.ArgumentParser();p.add_argument('--driver');p.add_argument('--slam-root',type=Path)
    p.add_argument('--camera',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    assert bool(a.driver)!=bool(a.slam_root)
    for case in (('exact',) if a.slam_root else ('exact','bad_crc','bad_id','simulated','truncated')):
        server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);port=server.getsockname()[1];errors=[]
        def model():
            try:
                conn,_=server.accept()
                with conn:
                    for i in range(1,25):
                        h=receive(conn,64);f=list(HEADER.unpack(h));pixels=receive(conn,691200)
                        assert f[:4]==[b'ORB60NET',1,64,1] and f[4:6]==[i,1000+i]
                        assert f[8]==0 and f[-2]==zlib.crc32(pixels) and pixels==bytes([i])*691200
                        b=bytearray(128+64+1024);struct.pack_into('<8I',b,0,1,0,0,0,0,0,0,0)
                        struct.pack_into('<8I',b,32,0,1,1,1,1,1,1,1)
                        struct.pack_into('<5I2iI',b,128,100,80,200,0,i%32,-3,4,(i%32)*737280)
                        b[160:192]=bytes((i+j)%256 for j in range(32))
                        for l in range(8):
                            at=192+l*128;n=int(l==0)
                            struct.pack_into('<5I',b,at,0x600003,0,l,WIDTHS[l],HEIGHTS[l]);struct.pack_into('<I',b,at+44,1)
                            struct.pack_into('<6I',b,at+64,0x600002,0,l,n,n,int(l>0));struct.pack_into('<I',b,at+104,1)
                        f[3]=2;f[9]=1;f[10]=len(b);f[11]=0;f[12]=zlib.crc32(b);f[13]=0
                        if i==2:
                            if case=='bad_crc':f[12]^=1
                            if case=='bad_id':f[4]+=1
                            if case=='simulated':f[13]=1
                        reply=HEADER.pack(*f);time.sleep(.002)
                        for chunk in (reply[:3],reply[3:],b[:17],b[17:]):
                            conn.sendall(chunk)
                            if i==2 and case=='truncated':return
                        if i==2 and case!='exact':
                            while conn.recv(65536):pass
                            return
            except Exception as exc:errors.append(repr(exc))
            finally:server.close()
        endpoint=f'127.0.0.1:{port}';env=os.environ.copy();cwd=None
        if a.slam_root:
            assert a.output and a.camera;a.output.mkdir(parents=True,exist_ok=False);cwd=a.output
            images=a.output/'fixture/mav0/cam0/data';images.mkdir(parents=True)
            for i in range(1,25):(images/f'{1000+i}.png').write_bytes(b'P5\n960 720\n255\n'+bytes([i])*691200)
            times=a.output/'timestamps.txt';times.write_text(''.join(f'{1000+i}\n' for i in range(1,25)))
            cmd=[str(a.slam_root/'Examples/Monocular/mono_euroc'),str(a.slam_root/'Vocabulary/ORBvoc.txt'),
                 str(a.camera),str(a.output/'fixture'),str(times),'--no-viewer','--unpaced',
                 '--feature-mode','fpga-pipeline','--feature-dir',endpoint]
            env['LD_LIBRARY_PATH']=str(a.slam_root.parent.parent/'install/lib')+':'+env.get('LD_LIBRARY_PATH','')
        else:cmd=[a.driver,endpoint]
        thread=threading.Thread(target=model,daemon=True);thread.start()
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=120 if a.slam_root else 20,cwd=cwd,env=env)
        thread.join(5);assert not thread.is_alive()
        if a.output:(a.output/'output.log').write_text(proc.stdout+'\n'+proc.stderr)
        if case=='exact':
            assert proc.returncode==0 and not errors,(proc.stdout,proc.stderr,errors)
            summary=re.search(r'FPGA_PIPELINE_SUMMARY sent=24 received=24 consumed=24 max_inflight=(\d+)',proc.stdout)
            assert summary and 1<=int(summary[1])<=3
            if not a.slam_root:assert int(summary[1])==3,'credit saturation not exercised'
            if a.slam_root:
                rows=list(csv.DictReader((a.output/'FeatureTimeStats.csv').open()))
                assert len(rows)==24 and all(int(r['extractor_calls'])==0 and int(r['count'])==1 for r in rows)
                assert [int(r['timestamp_ns']) for r in rows]==list(range(1001,1025))
                print('SYNTHETIC_SLAM_PRODUCER_CONSUMER_STARTUP_DRAIN_24_PASS; NOT_PHYSICAL_BOARD')
        else:
            reason=dict(bad_crc='pipeline reply CRC',bad_id='pipeline reply identity/ABI',
                        simulated='hardware error or simulated result refused',truncated='socket timeout/disconnect')[case]
            assert proc.returncode==23 and reason in proc.stderr,(case,proc.stdout,proc.stderr)
        print(case,'PASS',proc.stdout.splitlines()[-1:] if case=='exact' else proc.stderr.strip())
    print('SYNTHETIC_CPP_ASYNC_IDENTITY_OWNERSHIP_EXACT_ERROR_SHUTDOWN_PASS')


if __name__=='__main__':main()
