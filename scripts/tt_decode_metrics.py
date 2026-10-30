"""Bounded decoder metrics. These are processing times, not camera latency."""
from collections import deque
import json
from pathlib import Path
import time

import av
import numpy as np
from av.codec.hwaccel import HWAccel


def make_decoder(mode='software'):
    if mode not in ('software','d3d11va'):
        raise ValueError('Unknown decoder')
    accel = None if mode == 'software' else HWAccel('d3d11va',allow_software_fallback=False,
                                                   options={'vendor_id':'0x1002'})
    codec = av.CodecContext.create('h264','r',hwaccel=accel)
    codec.thread_count = 1
    return codec


class DecodeMetrics:
    def __init__(self,mode):
        self.mode = mode
        self.started, self.cpu_started = time.perf_counter(), time.process_time()
        self.decode = deque(maxlen=1800)
        self.convert = deque(maxlen=1800)
        self.frames = self.packets = self.errors = 0
        self.corrupt_frames = 0
        self.hardware = False

    def snapshot(self):
        elapsed = time.perf_counter()-self.started
        return dict(mode=self.mode,hardware_active=self.hardware,frames=self.frames,
                    packets=self.packets,errors=self.errors,corrupt_frames=self.corrupt_frames,elapsed_s=elapsed,
                    delivered_fps=self.frames/max(elapsed,.001),
                    process_cpu_percent_one_core=100*(time.process_time()-self.cpu_started)/max(elapsed,.001),
                    decode_call_ms={k:float(np.percentile(self.decode,p)) if self.decode else None
                                    for k,p in (('p50',50),('p95',95))},
                    convert_ms={k:float(np.percentile(self.convert,p)) if self.convert else None
                                for k,p in (('p50',50),('p95',95))},
                    definition='Decode call and BGR download/conversion; not camera/transport latency')

    def save(self,directory):
        if directory:
            target = Path(directory)/'pc_decode.json'
            tmp = target.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.snapshot(),indent=2),encoding='utf-8')
            tmp.replace(target)


def benchmark(path,mode,output):
    metrics = DecodeMetrics(mode)
    codec = make_decoder(mode)
    with av.open(str(path),format='h264') as source:
        for packet in source.demux(video=0):
            if not packet.size:
                continue
            before = time.perf_counter()
            frames = codec.decode(packet)
            metrics.decode.append((time.perf_counter()-before)*1000)
            metrics.packets += 1
            for frame in frames:
                metrics.corrupt_frames += bool(frame.is_corrupt)
                before = time.perf_counter()
                frame.to_ndarray(format='bgr24')
                metrics.convert.append((time.perf_counter()-before)*1000)
                metrics.frames += 1
        for frame in codec.decode(None):
            frame.to_ndarray(format='bgr24');metrics.frames += 1
    metrics.hardware = bool(codec.is_hwaccel)
    if mode != 'software' and not metrics.hardware:
        raise RuntimeError('Hardware decode was not activated; no fallback result accepted')
    Path(output).write_text(json.dumps(metrics.snapshot(),indent=2),encoding='utf-8')
    print(json.dumps(metrics.snapshot()),flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--mode',choices=('software','d3d11va'),required=True)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    benchmark(args.path,args.mode,args.output)
