"""Media-only SSH transport. No drone commands; bounded forwarding/preview."""
import json
from pathlib import Path
import queue
import struct
import subprocess
import threading
import time

import cv2
import numpy as np

HEADER = struct.Struct('!II')


def read_exact(stream,size):
    chunks = bytearray()
    while len(chunks)<size:
        data = stream.read(size-len(chunks))
        if not data:
            if chunks:
                raise EOFError('Truncated RK preview')
            return None
        chunks.extend(data)
    return bytes(chunks)


class RKBridge:
    def __init__(self,packets,output,alias='rk3588',script='orbslam3_cpu_baseline/runtime/tt_video/tt_rk_decode.py',preview_encoder='jpegenc'):
        if preview_encoder not in ('auto','jpegenc','mppjpegenc','mppjpegenc-copy'):
            raise ValueError('Unknown RK preview encoder')
        self.packets,self.output = packets,Path(output)
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.frame,self.received,self.stats = None,0,dict(event='starting')
        self.sent = {}
        self.log = (self.output/'rk_stderr.log').open('wb')
        self.process = subprocess.Popen(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10',
                                         alias,'python3 -u '+script+' --preview-encoder '+preview_encoder],stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,stderr=self.log,bufsize=0)
        self.writer = threading.Thread(target=self.write_loop,daemon=True)
        self.reader = threading.Thread(target=self.read_loop,daemon=True)
        self.writer.start();self.reader.start()

    def fail(self,error):
        with self.lock:
            self.stats.update(event='error',error=str(error))
        self.ready.set()

    def write_loop(self):
        try:
            while not self.stop.is_set():
                try:
                    value = self.packets.get(timeout=.1)
                except queue.Empty:
                    continue
                if value is None:
                    break
                tag,source_time,payload = value
                with self.lock:
                    self.sent[tag] = source_time
                    if len(self.sent)>2048:
                        self.sent.pop(next(iter(self.sent)))
                # Binary pipe writes may be short; use a buffered stream wrapper.
                message = HEADER.pack(tag,len(payload))+payload
                view = memoryview(message)
                while view:
                    size = self.process.stdin.write(view)
                    if not size:
                        raise BrokenPipeError('RK stdin closed')
                    view = view[size:]
        except (OSError,ValueError) as exc:
            if not self.stop.is_set():
                self.fail(exc)
        finally:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def read_loop(self):
        try:
            while True:
                header = read_exact(self.process.stdout,HEADER.size)
                if header is None:
                    break
                meta_size,jpeg_size = HEADER.unpack(header)
                if meta_size>65536 or jpeg_size>8*1024*1024:
                    raise ValueError('Invalid RK media message')
                metadata = json.loads(read_exact(self.process.stdout,meta_size))
                jpeg = read_exact(self.process.stdout,jpeg_size) if jpeg_size else None
                now = time.perf_counter()
                image = cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR) if jpeg else None
                if jpeg and image is None:
                    raise ValueError('Invalid RK JPEG')
                with self.lock:
                    self.stats.update(metadata)
                    if image is not None:
                        self.frame,self.received = image,now
                        origin = self.sent.pop(metadata['tag'],None)
                        self.stats['pc_packet_to_preview_ms'] = (now-origin)*1000 if origin else None
                self.ready.set()
        except Exception as exc:
            self.fail(exc)
        finally:
            if not self.ready.is_set():
                self.fail('RK decoder exited before readiness; inspect rk_stderr.log')
            elif self.latest()[2].get('event') not in ('done','error'):
                self.fail('RK decoder exited without completion; inspect rk_stderr.log')

    def latest(self):
        with self.lock:
            return self.frame,self.received,dict(self.stats)

    def save(self):
        _,_,stats = self.latest()
        (self.output/'rk_decode.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')

    def close(self):
        try:
            self.packets.put(None,timeout=2)
        except queue.Full:
            self.fail('RK shutdown input queue did not drain')
        self.writer.join(2)
        self.stop.set()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)
        self.reader.join(2)
        if self.process.returncode != 0 and self.latest()[2].get('event') != 'error':
            self.fail('RK SSH/media process exit code '+str(self.process.returncode))
        with self.lock:
            self.stats['ssh_exit_code'] = self.process.returncode
        self.save()
        self.log.close()
