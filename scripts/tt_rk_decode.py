"""RK3588 media-only SSH pipe: framed H.264 in, decoded JPEG preview out.

Requires system python3 + gi/GStreamer + mppvideodec. No UDP/TT/flight commands.
The MPP src pad is timed BEFORE preview JPEG conversion and SSH return.
"""
import json
import struct
import sys
import threading
import time
from collections import deque
import resource
import os
import argparse

import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst

Gst.init(None)
HEADER = struct.Struct('!II')
TAG_NS = 33333333


def read_exact(source,size):
    parts = bytearray()
    while len(parts)<size:
        chunk = source.read(size-len(parts))
        if not chunk:
            if parts:
                raise EOFError('Truncated media message')
            return None
        parts.extend(chunk)
    return bytes(parts)


def run(preview_encoder='jpegenc'):
    if preview_encoder == 'auto':
        preview_encoder = 'mppjpegenc' if Gst.ElementFactory.find('mppjpegenc') else 'jpegenc'
    # SSH needs CPU-readable bytes, not retained MPP packet-pool buffers.
    if preview_encoder in ('mppjpegenc','mppjpegenc-copy'):
        preview_path = 'mppjpegenc rc-mode=fixqp q-factor=85 zero-copy-pkt=false'
        if preview_encoder == 'mppjpegenc-copy':
            preview_path = 'videoconvert ! video/x-raw,format=I420 ! '+preview_path
    else:
        preview_path = 'videoconvert ! video/x-raw,format=I420 ! jpegenc quality=85'
    pipeline = Gst.parse_launch(
        'appsrc name=src is-live=true format=time block=true max-bytes=2097152 '
        'caps="video/x-h264,stream-format=byte-stream,alignment=au,framerate=30/1" ! h264parse config-interval=-1 ! '
        'mppvideodec name=decoder ignore-error=true fast-mode=true ! identity name=decoded ! '
        'queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream ! '
        +preview_path+' ! appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true enable-last-sample=false')
    appsrc, sink = pipeline.get_by_name('src'), pipeline.get_by_name('sink')
    bus = pipeline.get_bus()
    lock, write_lock = threading.Lock(), threading.Lock()
    pending, delays = {}, deque(maxlen=1800)
    decoded_times, preview_times = deque(maxlen=90), deque(maxlen=90)
    started = time.perf_counter()
    start_cpu = resource.getrusage(resource.RUSAGE_SELF)
    state = dict(decoded=0,preview=0,packets=0,decoder='mppvideodec',hardware_active=True,
                 preview_encoder=preview_encoder,
                 first_tag=None,last_tag=None,skipped_tag_ranges=[],
                 error_policy='MPP plugin default ignore-error=true for preview; does not prove clean frames')

    def snapshot():
        with lock:
            result = dict(state)
            ordered = sorted(delays)
            for name,times in (('decode_fps',decoded_times),('preview_fps',preview_times)):
                result[name] = (len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0
        elapsed = time.perf_counter()-started
        cpu = resource.getrusage(resource.RUSAGE_SELF)
        result.update(elapsed_s=elapsed,delivered_fps=result['decoded']/max(elapsed,.001),
                      process_cpu_percent_one_core=100*(cpu.ru_utime+cpu.ru_stime-start_cpu.ru_utime-start_cpu.ru_stime)/max(elapsed,.001),
                      input_to_mpp_output_ms={k:ordered[min(len(ordered)-1,int((len(ordered)-1)*p))] if ordered else None
                                              for k,p in (('p50',.5),('p95',.95))},
                      definition='RK packet arrival to MPP decoded frame; preview/SSH return excluded; CPU includes preview encoding')
        return result

    def send(metadata,payload=b''):
        data = json.dumps(metadata).encode('utf-8')
        with write_lock:
            sys.stdout.buffer.write(HEADER.pack(len(data),len(payload)))
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()

    def decoded_probe(pad,info):
        buffer = info.get_buffer()
        if buffer is not None:
            tag = int(round(buffer.pts/TAG_NS))
            with lock:
                origin = pending.pop(tag,None)
                state['decoded'] += 1
                decoded_times.append(time.perf_counter())
                if state['first_tag'] is None:
                    state['first_tag'] = tag
                if state['last_tag'] is not None and tag > state['last_tag']+1:
                    state['skipped_tag_ranges'].append([state['last_tag']+1,tag-1])
                    state['skipped_tag_ranges'] = state['skipped_tag_ranges'][-12:]
                state['last_tag'] = tag
                if origin is not None:
                    delays.append((time.perf_counter()-origin)*1000)
        return Gst.PadProbeReturn.OK

    def preview_ready(appsink):
        sample = appsink.emit('pull-sample')
        buffer = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        ok, mapped = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR
        try:
            payload = bytes(mapped.data)
        finally:
            buffer.unmap(mapped)
        with lock:
            state['preview'] += 1
            preview_times.append(time.perf_counter())
        try:
            send(dict(event='frame',tag=int(round(buffer.pts/TAG_NS)),
                      width=caps.get_value('width'),height=caps.get_value('height'),**snapshot()),payload)
        except (BrokenPipeError,OSError):
            return Gst.FlowReturn.ERROR
        return Gst.FlowReturn.OK

    pipeline.get_by_name('decoded').get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER,decoded_probe)
    sink.connect('new-sample',preview_ready)
    pipeline.set_state(Gst.State.PLAYING)
    send(dict(event='ready',decoder='mppvideodec',hardware_active=True,preview_encoder=preview_encoder))
    try:
        while True:
            header = read_exact(sys.stdin.buffer,HEADER.size)
            if header is None:
                break
            tag, size = HEADER.unpack(header)
            if not 0<size<=4*1024*1024:
                raise ValueError('Invalid H.264 packet size')
            payload = read_exact(sys.stdin.buffer,size)
            if payload is None:
                raise EOFError('Missing payload')
            buffer = Gst.Buffer.new_allocate(None,size,None)
            buffer.fill(0,payload)
            buffer.pts = buffer.dts = tag*TAG_NS
            buffer.duration = TAG_NS
            with lock:
                state['packets'] += 1
                pending[tag] = time.perf_counter()
                if len(pending)>2048:
                    pending.pop(next(iter(pending)))
            if appsrc.emit('push-buffer',buffer) != Gst.FlowReturn.OK:
                raise RuntimeError('MPP pipeline refused input')
            message = bus.timed_pop_filtered(0,Gst.MessageType.ERROR)
            if message:
                error,detail = message.parse_error()
                raise RuntimeError(str(error)+' '+str(detail))
        appsrc.emit('end-of-stream')
        message = bus.timed_pop_filtered(5*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
        if message is None:
            raise RuntimeError('MPP EOS completion timed out')
        if message.type == Gst.MessageType.ERROR:
            raise RuntimeError(str(message.parse_error()))
        send(dict(event='done',**snapshot()))
    except Exception as exc:
        send(dict(event='error',error=str(exc),**snapshot()))
        return 1
    finally:
        # A failed native plugin can also block its NULL transition. Bound
        # cleanup so a media-only helper cannot remain on the board forever.
        cleanup = threading.Thread(target=pipeline.set_state,args=(Gst.State.NULL,),daemon=True)
        cleanup.start()
        cleanup.join(3)
        if cleanup.is_alive():
            sys.stderr.write('MPP pipeline shutdown timed out\n')
            sys.stderr.flush()
            os._exit(1)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-encoder',choices=('auto','jpegenc','mppjpegenc','mppjpegenc-copy'),default='jpegenc')
    raise SystemExit(run(parser.parse_args().preview_encoder))
