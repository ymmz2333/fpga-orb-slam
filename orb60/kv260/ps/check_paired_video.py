"""Exercise the actual native paired FIFO parser; no SLAM/PL/DPU execution."""
import argparse
import errno
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
import threading
import time
import zlib
import numpy as np
import cv2


def run(executable,output):
    if platform.system()!='Linux' or platform.machine()!='aarch64':raise ValueError('Native KV260 required')
    executable=Path(executable).resolve();output=Path(output).resolve();output.mkdir(exist_ok=False)
    bgr=np.arange(720*960*3,dtype=np.uint32).astype(np.uint8).reshape(720,960,3)
    gray=np.full((720,960),19,np.uint8)  # Deliberately differs from BGR2GRAY.
    bc,gc=zlib.crc32(bgr.tobytes()),zlib.crc32(gray.tobytes());stamp=1793620000123456789
    def packet(i,**kw):return struct.pack('<8sQQII',kw.get('magic',b'ORBPAIR1'),kw.get('index',i),kw.get('stamp',stamp+i),bc,gc)+bgr.tobytes()+gray.tobytes()
    a,b=packet(0),packet(1);rgb_bad=bytearray(a);rgb_bad[32+123]^=1;gray_bad=bytearray(a);gray_bad[-123]^=1
    legacy_gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY);legacy_gc=zlib.crc32(legacy_gray.tobytes())
    cases=[('paired_two',a+b,2,True,False,gc),('rgb_corrupt',bytes(rgb_bad),1,False,False,gc),
           ('gray_corrupt',bytes(gray_bad),1,False,False,gc),('wrong_index',packet(0,index=1),1,False,False,gc),
           ('wrong_stamp',packet(0,stamp=stamp+1),1,False,False,gc),('wrong_magic',packet(0,magic=b'BADPAIR1'),1,False,False,gc),
           ('wrong_gray_identity',a,1,False,False,gc^1),('truncated_header',a[:31],1,False,False,gc),
           ('truncated_rgb',a[:1000],1,False,False,gc),('truncated_gray',a[:-1],1,False,False,gc),
           ('extra_source',a+b,1,False,False,gc),('missing_source',b'',1,False,False,gc),
           ('legacy_raw',bgr.tobytes()*2,2,True,True,legacy_gc)]
    records=[]
    for name,data,count,success,raw,expected_crc in cases:
        with tempfile.TemporaryDirectory(prefix='pair_gate_',dir=output) as temp:
            folder=Path(temp);fifo=folder/'video.fifo';os.mkfifo(fifo,0o600)
            ids=folder/'identities.csv';ids.write_text('source_frame_id,timestamp_ns,gray_crc\n'+''.join('%d,%d,%d\n'%(i,stamp+i,expected_crc) for i in range(count)))
            child=subprocess.Popen([str(executable),'--verify-video',('pipe:' if raw else 'paired:')+str(fifo),str(ids)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            failures=[]
            def writer():
                fd=None
                try:
                    end=time.monotonic()+10
                    while fd is None:
                        try:fd=os.open(fifo,os.O_WRONLY|os.O_NONBLOCK)
                        except OSError as e:
                            if e.errno!=errno.ENXIO:raise
                            if child.poll() is not None or time.monotonic()>end:raise RuntimeError('Native FIFO consumer did not open')
                            time.sleep(.01)
                    os.set_blocking(fd,True);view=memoryview(data)
                    while view:
                        n=os.write(fd,view);view=view[n:]
                except BrokenPipeError:pass
                except BaseException as e:failures.append(repr(e))
                finally:
                    if fd is not None:os.close(fd)
            thread=threading.Thread(target=writer,daemon=True);thread.start()
            try:logs=child.communicate(timeout=15)[0].decode(errors='replace')
            finally:
                if child.poll() is None:child.kill();child.wait()
            thread.join(12)
            if thread.is_alive() or failures or ((child.returncode==0)!=success) or (success and 'NATIVE_VIDEO_IDENTITY_PASS' not in logs):
                raise ValueError('Native parser gate failed: '+name+' '+repr(failures)+' '+logs[-1000:])
            records.append(dict(case=name,expected_success=success,exit_code=child.returncode,output=logs.strip()))
    value=dict(status='NATIVE_PAIRED_VIDEO_PARSER_PASS',scope='13 real native FIFO cases; independent non-BGR-derived gray, original raw compatibility, CRC/identity/truncation/extra/missing failures; no whole-system claim',cases=records)
    (output/'RESULT.json').write_text(json.dumps(value,indent=2)+'\n');print(value['status'],len(records),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--executable',required=True);p.add_argument('--output',required=True)
    run(**vars(p.parse_args()))
