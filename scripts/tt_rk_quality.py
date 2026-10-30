"""Local RK MPP quality capture, without JPEG, SSH streaming or drone commands.

Save selected decoded Y planes (PGM) and RGB frames (PPM), using negotiated
GStreamer offsets/strides. System Python 3.8 + GI is sufficient.
"""
import argparse
import json
from pathlib import Path
import threading
import time

import gi
gi.require_version('Gst','1.0')
gi.require_version('GstVideo','1.0')
from gi.repository import Gst, GstVideo

Gst.init(None)
SELECTED = {29,149,269}


def save_plane(buffer,caps,output,index,rgb):
    info = GstVideo.VideoInfo()
    if not info.from_caps(caps):
        raise RuntimeError('Cannot read negotiated video info')
    fmt = info.finfo.name
    if (rgb and fmt != 'RGB') or (not rgb and fmt not in ('NV12','I420')):
        raise RuntimeError('Unexpected capture format '+fmt)
    row_bytes = info.width*(3 if rgb else 1)
    offset,stride = info.offset[0],info.stride[0]
    ok,mapped = buffer.map(Gst.MapFlags.READ)
    if not ok:
        raise RuntimeError('Cannot map decoded frame')
    try:
        if stride<row_bytes or offset+(info.height-1)*stride+row_bytes>len(mapped.data):
            raise RuntimeError('Decoded buffer layout is invalid')
        rows = b''.join(bytes(mapped.data[offset+y*stride:offset+y*stride+row_bytes])
                        for y in range(info.height))
    finally:
        buffer.unmap(mapped)
    suffix,magic = ('ppm','P6') if rgb else ('pgm','P5')
    (output/('frame_%03d.%s'%(index,suffix))).write_bytes(
        ('%s\n%d %d\n255\n'%(magic,info.width,info.height)).encode('ascii')+rows)
    return dict(format=fmt,width=info.width,height=info.height,stride=stride,
                caps=caps.to_string())


def run(source,output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    pipeline = Gst.parse_launch(
        'filesrc name=source ! h264parse ! mppvideodec ignore-error=true fast-mode=true '
        '! identity name=decoded ! videoconvert ! video/x-raw,format=RGB '
        '! appsink name=sink emit-signals=true sync=false max-buffers=2 drop=false enable-last-sample=false')
    pipeline.get_by_name('source').set_property('location',str(Path(source).resolve()))
    state = dict(decoded=0,rgb_frames=0,y_saved=[],rgb_saved=[],errors=[],
                 decoder='mppvideodec',jpeg_used=False,
                 error_policy='ignore-error=true; frame count is not proof of absence of source damage')
    started = time.perf_counter()

    def decoded(pad,probe):
        index = state['decoded']
        state['decoded'] += 1
        if index in SELECTED:
            try:
                state['y_layout'] = save_plane(probe.get_buffer(),pad.get_current_caps(),output,index,False)
                state['y_saved'].append(index)
            except Exception as exc:
                state['errors'].append(str(exc))
        return Gst.PadProbeReturn.OK

    def rgb_ready(sink):
        sample = sink.emit('pull-sample')
        index = state['rgb_frames']
        state['rgb_frames'] += 1
        if index in SELECTED:
            try:
                state['rgb_layout'] = save_plane(sample.get_buffer(),sample.get_caps(),output,index,True)
                state['rgb_saved'].append(index)
            except Exception as exc:
                state['errors'].append(str(exc))
        return Gst.FlowReturn.OK

    pipeline.get_by_name('decoded').get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER,decoded)
    pipeline.get_by_name('sink').connect('new-sample',rgb_ready)
    pipeline.set_state(Gst.State.PLAYING)
    message = pipeline.get_bus().timed_pop_filtered(25*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
    if message is None:
        state['errors'].append('Local decode EOS timeout')
    elif message.type == Gst.MessageType.ERROR:
        state['errors'].append(str(message.parse_error()))
    state['elapsed_s'] = time.perf_counter()-started
    cleanup = threading.Thread(target=pipeline.set_state,args=(Gst.State.NULL,),daemon=True)
    cleanup.start();cleanup.join(3)
    if cleanup.is_alive():
        state['errors'].append('Local decode shutdown timeout')
    state['passed'] = (not state['errors'] and state['decoded']==state['rgb_frames']
                       and set(state['y_saved'])==SELECTED and set(state['rgb_saved'])==SELECTED)
    (output/'quality_capture.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    print(json.dumps(state),flush=True)
    return 0 if state['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    raise SystemExit(run(args.source,args.output))
