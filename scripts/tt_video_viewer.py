"""Windows TT live viewer: dedicated decoding process, one latest-frame slot.

Only SDK/video commands are permitted. No motor or flight controls exist.
85 C is displayed, not treated as a manufacturer-specified cutoff.
Launch with run_tt_video_viewer.ps1 to load the project environment.
"""
from collections import deque
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import ipaddress
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import select
import socket
import struct
import time

import av
import cv2
import numpy as np
from tt_latency_recording import TARGET_WINDOW, timing_pattern
from tt_video_capture import CaptureControls, RecorderSink
from tt_video_config import DEFAULT_BITRATE, video_settings
from tt_decode_metrics import DecodeMetrics, make_decoder
from tt_rk_bridge import RKBridge
from tt_record_button import WindowsRecordInput, RecordButton

ALLOWED_COMMANDS = frozenset({
    'command', 'battery?', 'setresolution high', *(f'setbitrate {i}' for i in range(6)),
    'setfps high', 'streamon', 'streamoff',
})
MAX_BYTES = 1280 * 720 * 3
WINDOW = 'TT LIVE VIDEO - no flight controls - Esc to close'
# Shared metadata: sequence, timestamp, width, height, fps, battery,
# board_min, board_max, total_bytes, decode_errors, telemetry_timestamp.
# Optional flight-station extension (14 slots): height, height_timestamp,
# battery_timestamp. The 11-slot video-only viewer does not use flight state.


def update_telemetry(data, meta, timestamp):
    values = {}
    for field in data.decode('ascii', 'replace').split(';'):
        if ':' not in field:
            continue
        key, value = field.split(':', 1)
        if key not in ('bat', 'templ', 'temph', 'h'):
            continue
        try:
            number = float(value)
            if math.isfinite(number):
                values[key] = number
        except ValueError:
            pass
    with meta.get_lock():
        for key, index in [('bat', 5), ('templ', 6), ('temph', 7)]:
            if key in values:
                meta[index] = values[key]
        if values:
            meta[10] = timestamp
        if len(meta) >= 14:
            if 'h' in values and -20 <= values['h'] <= 3000:
                meta[11:13] = [values['h'], timestamp]
            if 'bat' in values and 0 <= values['bat'] <= 100:
                meta[13] = timestamp


def encode_command(command):
    if command not in ALLOWED_COMMANDS:
        raise ValueError('Blocked: not an allowed SDK/video command')
    return command.encode('ascii')


def bind_udp(local_ip, interface, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack('!I', interface))
        sock.bind((local_ip, port))
        return sock
    except BaseException:
        sock.close()
        raise


def verify_peer(local_ip, drone_ip, expected_mac):
    api = ctypes.WinDLL('iphlpapi.dll').SendARP
    api.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
                    ctypes.POINTER(wintypes.ULONG)]
    buf = (ctypes.c_ubyte * 8)()
    size = wintypes.ULONG(8)
    result = api(int.from_bytes(socket.inet_aton(drone_ip), 'little'),
                 int.from_bytes(socket.inet_aton(local_ip), 'little'),
                 buf, ctypes.byref(size))
    actual = ':'.join(f'{x:02x}' for x in buf[:size.value])
    if result or actual.lower() != expected_mac.replace('-', ':').lower():
        raise RuntimeError(f'TT identity check failed at {drone_ip}: ARP={result}, MAC={actual}')


def receive_video(local_ip, drone_ip, interface, buffer, meta, ready, stop, errors, control,
                  recording_status=None, decoder_mode='software', mirror=None, diagnostics=None):
    """Bounded latest-frame decoder; optional original-packet recording, no encoding."""
    handles = []
    recorder = RecorderSink(recording_status)
    metrics = DecodeMetrics(decoder_mode)
    last_metrics = 0.
    try:
        video = bind_udp(local_ip, interface, 11111); handles.append(video)
        state = bind_udp(local_ip, interface, 8890); handles.append(state)
        video.setblocking(False); state.setblocking(False)
        codec = make_decoder(decoder_mode)
        cv2.setNumThreads(1)
        shared = np.frombuffer(buffer, dtype=np.uint8)
        times = deque(maxlen=90)
        sequence = total_bytes = decode_errors = packet_tag = 0
        ready.set()
        while not stop.is_set():
            while True:
                try: action = control.get_nowait()
                except queue.Empty: break
                if action['action'] == 'start': recorder.start(action['directory'],action.get('kind','latency'),action.get('metadata'))
                elif action['action'] == 'stop': recorder.close()
            available, _, _ = select.select([state, video], [], [], .1)
            for sock in available:
                # Bounded batches let telemetry and shutdown remain responsive.
                for _ in range(64):
                    try:
                        data, peer = sock.recvfrom(65535)
                    except BlockingIOError:
                        break
                    if peer[0] != drone_ip:
                        continue
                    if sock is state:
                        update_telemetry(data, meta, time.perf_counter())
                        continue
                    total_bytes += len(data)
                    try:
                        for packet in codec.parse(data):
                            packet_tag += 1
                            packet.pts = packet_tag; packet.dts = packet_tag
                            recorder.packet(bytes(packet),packet_tag,time.perf_counter(),packet.is_keyframe)
                            if mirror is not None:
                                try:
                                    mirror.put_nowait((packet_tag,time.perf_counter(),bytes(packet)))
                                except queue.Full:
                                    errors.put('RK forwarding queue full: comparison is incomplete; PC video continues')
                                    mirror = None
                            before = time.perf_counter()
                            decoded = codec.decode(packet)
                            metrics.decode.append((time.perf_counter()-before)*1000)
                            metrics.packets += 1
                            metrics.hardware = bool(codec.is_hwaccel)
                            for frame in decoded:
                                metrics.corrupt_frames += bool(frame.is_corrupt)
                                before = time.perf_counter()
                                image = frame.to_ndarray(format='bgr24')
                                metrics.convert.append((time.perf_counter()-before)*1000)
                                metrics.frames += 1
                                if image.size > MAX_BYTES:
                                    raise RuntimeError(f'Unexpected video dimensions: {image.shape}')
                                timestamp = time.perf_counter()
                                recorder.frame(frame.pts,timestamp,frame.width,frame.height)
                                times.append(timestamp)
                                fps = (len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0
                                sequence += 1
                                with meta.get_lock():
                                    shared[:image.size] = image.ravel()
                                    meta[0:5] = [sequence, timestamp, frame.width, frame.height, fps]
                                    meta[8:10] = [total_bytes, decode_errors]
                    except av.error.FFmpegError:
                        decode_errors += 1
                        metrics.errors += 1
            if time.perf_counter()-last_metrics>=3:
                metrics.save(diagnostics)
                last_metrics = time.perf_counter()
    except Exception as exc:
        errors.put(str(exc)); stop.set()
    finally:
        recorder.close()
        metrics.save(diagnostics)
        for sock in handles: sock.close()


def self_test():
    for value in ALLOWED_COMMANDS:
        assert encode_command(value).decode('ascii') == value
    for value in ('takeoff', 'motoron', 'motoroff', 'emergency', 'rc 0 0 0 0',
                  'land', 'command\nmotoron', 'streamon\r\ntakeoff'):
        try: encode_command(value)
        except ValueError: pass
        else: raise AssertionError('Unsafe command accepted: ' + value)
    ctx = mp.get_context('spawn')
    buffer = ctx.RawArray('B', MAX_BYTES)
    meta = ctx.Array('d', 11)
    frame = np.full((720,960,3), 123, np.uint8)
    with meta.get_lock():
        np.frombuffer(buffer,dtype=np.uint8)[:frame.size] = frame.ravel()
        meta[0:4] = [1, time.perf_counter(), 960, 720]
    with meta.get_lock():
        copy = np.frombuffer(buffer,dtype=np.uint8)[:frame.size].copy().reshape(720,960,3)
    assert np.array_equal(frame,copy)
    print('PASS: exact video-command allowlist; latest-frame shared-memory roundtrip; no network used')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-ip'); parser.add_argument('--drone-ip')
    parser.add_argument('--interface', type=int)
    parser.add_argument('--expected-mac')
    parser.add_argument('--seconds', type=float, default=0, help='0: until window closed')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--capture-kind', choices=('flight','handheld'), default='handheld')
    parser.add_argument('--bitrate', type=int, choices=range(6), default=DEFAULT_BITRATE)
    parser.add_argument('--decoder', choices=('software','d3d11va'), default='software')
    parser.add_argument('--compare-rk',type=int,choices=(0,1),default=0)
    parser.add_argument('--rk-preview-encoder',choices=('jpegenc','mppjpegenc-copy'),default='jpegenc')
    parser.add_argument('--auto-record',action='store_true',help='Video-only capture starts at first live frame')
    parser.add_argument('--controller-index',type=int,choices=range(4),default=0)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not all((args.local_ip,args.drone_ip,args.interface,args.expected_mac)):
        parser.error('Use run_tt_video_viewer.ps1, or supply all network/identity arguments')
    if args.seconds < 0: parser.error('--seconds cannot be negative')
    network = ipaddress.ip_network(args.local_ip+'/24',strict=False)
    if ipaddress.ip_address(args.drone_ip) not in network or args.drone_ip == args.local_ip:
        parser.error('Drone must be a different address on the selected local /24')
    verify_peer(args.local_ip,args.drone_ip,args.expected_mac)
    root = Path(os.environ['FPGA_PROJECT_ROOT'])
    output = root/'.work'/'tt-video-viewer'/datetime.now().strftime('%Y%m%dT%H%M%S_%f')
    output.mkdir(parents=True,exist_ok=False)
    summary = dict(local_ip=args.local_ip,drone_ip=args.drone_ip,commands=[],
        bitrate=args.bitrate,pc_decoder=args.decoder,compare_rk=bool(args.compare_rk),
        output=str(output),mode='video only',frames=0,
        temperature_policy='display only; no invented 85 C shutdown threshold',
        latency_policy='No end-to-end video latency is claimed by this viewer')
    ctx = mp.get_context('spawn')
    buffer = ctx.RawArray('B',MAX_BYTES); meta = ctx.Array('d',11)
    meta[5:8] = [-1,-1,-1]
    ready = ctx.Event(); stop = ctx.Event(); errors = ctx.Queue(); control = ctx.Queue()
    recording_status = ctx.Queue()
    capture = CaptureControls(ctx,control,recording_status,root/'recordings'/'tt',args.capture_kind,
                              dict(bitrate=args.bitrate,resolution='high',fps='high'))
    mirror = ctx.Queue(128) if args.compare_rk else None
    bridge = None
    worker = ctx.Process(target=receive_video,args=(args.local_ip,args.drone_ip,args.interface,
        buffer,meta,ready,stop,errors,control,recording_status,args.decoder,mirror,str(output)),daemon=True)
    cmd = bind_udp(args.local_ip,args.interface,8889)
    cmd.connect((args.drone_ip,8889));cmd.settimeout(.12)
    attempted_stream = False
    recording = None
    record_button = RecordButton()
    record_input = None

    def request(value, timeout=2):
        payload = encode_command(value)
        while True:
            try: cmd.recv(4096)
            except socket.timeout: break
        cmd.send(payload);deadline=time.perf_counter()+timeout;replies=[]
        while time.perf_counter()<deadline:
            try: replies.append(cmd.recv(4096).decode('ascii','replace').strip('\0\r\n '))
            except socket.timeout:
                if replies: break
        row=dict(command=value,replies=replies);summary['commands'].append(row)
        print(json.dumps(row),flush=True);return 'ok' in replies

    def save_status():
        temporary=output/'status.tmp'
        temporary.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        temporary.replace(output/'status.json')

    def start_recording():
        nonlocal recording
        if recording is not None or capture.active is not None or capture.state == 'STOPPING': return
        directory = output / datetime.now().strftime('latency_%H%M%S_%f')
        directory.mkdir(exist_ok=False)
        pattern_log=(directory/'pattern.jsonl').open('x',encoding='utf-8')
        control.put(dict(action='start',directory=str(directory)))
        recording=dict(directory=directory,log=pattern_log,started=time.perf_counter(),
                       last_pattern=0.,tick=0)
        cv2.namedWindow(TARGET_WINDOW,cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(TARGET_WINDOW,600,650);cv2.moveWindow(TARGET_WINDOW,850,45)
        summary.setdefault('recordings',[]).append(str(directory))
        summary['recording_active']=True
        print('RECORDING_STARTED '+str(directory),flush=True)

    def stop_recording():
        nonlocal recording
        if recording is None: return
        control.put(dict(action='stop'))
        recording['log'].close()
        try: cv2.destroyWindow(TARGET_WINDOW)
        except cv2.error: pass
        summary['last_recording']=str(recording['directory'])
        summary['recording_active']=False
        print('RECORDING_STOP_REQUESTED '+str(recording['directory']),flush=True)
        recording=None
        save_status()

    try:
        cv2.setNumThreads(1)
        try:
            record_input = WindowsRecordInput(args.controller_index)
        except OSError as exc:
            summary['gamepad_record_error'] = str(exc)
            print('Xbox recording input unavailable; keyboard R remains usable: '+str(exc),flush=True)
        if mirror is not None:
            bridge = RKBridge(mirror,output,preview_encoder=args.rk_preview_encoder)
            if not bridge.ready.wait(12) or bridge.latest()[2].get('event') == 'error':
                raise RuntimeError('RK MPP media bridge startup failed; inspect rk_stderr.log')
            cv2.namedWindow('RK3588 MPP - decoded preview via SSH',cv2.WINDOW_NORMAL)
            cv2.resizeWindow('RK3588 MPP - decoded preview via SSH',800,640)
            cv2.moveWindow('RK3588 MPP - decoded preview via SSH',850,45)
        cv2.namedWindow(WINDOW,cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(WINDOW,800,655);cv2.moveWindow(WINDOW,25,45)
        waiting=np.zeros((784,960,3),np.uint8)
        cv2.putText(waiting,'Connecting to TT video... NO FLIGHT CONTROLS',(35,360),
                    cv2.FONT_HERSHEY_SIMPLEX,.85,(255,255,255),2)
        cv2.imshow(WINDOW,waiting);cv2.waitKey(1)
        if not any(request('command') for _ in range(3)):
            raise RuntimeError('No SDK acknowledgement. Check drone power and station IP.')
        for command in video_settings(args.bitrate):
            if not request(command): raise RuntimeError('Setting not acknowledged: '+command)
        worker.start()
        if not ready.wait(4) or stop.is_set(): raise RuntimeError('Video receiver startup failed')
        attempted_stream=True
        if not request('streamon'): raise RuntimeError('Stream start not acknowledged')
        started=last_stats=last_keepalive=time.perf_counter()
        last_sequence=0;last_image=None;first_saved=False;auto_record_started=False
        while not stop.is_set():
            now=time.perf_counter()
            capture.poll()
            summary.update(capture.snapshot())
            if bridge is not None:
                rk_image,rk_time,rk_stats = bridge.latest()
                summary['rk_decode'] = rk_stats
                if rk_image is not None:
                    rk_canvas = np.zeros((rk_image.shape[0]+64,rk_image.shape[1],3),np.uint8)
                    rk_canvas[:rk_image.shape[0]] = rk_image
                    lines = [f"RK H264 HW {rk_stats.get('decode_fps',0):.1f} fps | preview {rk_stats.get('preview_fps',0):.1f} fps | age {max(0,now-rk_time):.2f}s",
                             f"{rk_image.shape[1]}x{rk_image.shape[0]} source | JPEG preview only | decoded {rk_stats.get('decoded')} (NOT camera latency)"]
                    for index,line in enumerate(lines):
                        cv2.putText(rk_canvas,line,(12,rk_image.shape[0]+24+index*26),cv2.FONT_HERSHEY_SIMPLEX,.48,(220,220,220),1)
                    cv2.imshow('RK3588 MPP - decoded preview via SSH',rk_canvas)
                    if not (output/'rk_preview.png').exists():
                        cv2.imwrite(str(output/'rk_preview.png'),rk_image)
                if rk_stats.get('event') == 'error':
                    raise RuntimeError('RK decoding failed: '+rk_stats.get('error','unknown'))
            if recording is not None:
                if now-recording['started']>=10:
                    stop_recording()
                elif now-recording['last_pattern']>=.05:
                    code=(recording['tick']*73)%1000
                    image=timing_pattern(code);submitted=time.perf_counter()
                    cv2.imshow(TARGET_WINDOW,image)
                    recording['log'].write(json.dumps(dict(id=code,t_submit=submitted))+'\n')
                    recording['tick']+=1;recording['last_pattern']=submitted
            if args.seconds and now-started>=args.seconds: break
            if cv2.getWindowProperty(WINDOW,cv2.WND_PROP_VISIBLE)<1: break
            if not worker.is_alive(): raise RuntimeError('Video receiver process exited')
            with meta.get_lock():
                values=list(meta)
                seq=int(values[0]);width=int(values[2]);height=int(values[3])
                if seq!=last_sequence and width and height:
                    last_image=np.frombuffer(buffer,dtype=np.uint8)[:width*height*3].copy().reshape(height,width,3)
                    last_sequence=seq
            if last_image is not None:
                if args.auto_record and not auto_record_started:
                    capture.toggle(True)
                    auto_record_started=True
                # Only the newest decoded frame is shown; old GUI frames never queue.
                frame=last_image
                canvas=np.zeros((frame.shape[0]+64,frame.shape[1],3),np.uint8)
                canvas[:frame.shape[0]]=frame
                stale=now-values[1]>2
                color=(0,100,255) if stale or (0<=values[5]<15) else (230,230,230)
                line=f'{width}x{height} | {args.decoder} {values[4]:.1f} fps | {args.bitrate} Mbps | Battery {values[5]:.0f}%'
                cv2.putText(canvas,line,(12,frame.shape[0]+24),cv2.FONT_HERSHEY_SIMPLEX,.6,color,1)
                hint='VIDEO STALE - check connection/power' if stale else capture.label()
                if capture.active is not None:
                    hint=capture.label()
                if recording is not None:
                    hint=f'RECORDING {10-(now-recording["started"]):.1f}s left - point camera at black/white target | R: stop'
                else:
                    hint += ' | Xbox Y: start/stop REC'
                cv2.putText(canvas,hint,(12,frame.shape[0]+50),cv2.FONT_HERSHEY_SIMPLEX,.55,color,1)
                cv2.imshow(WINDOW,canvas)
                if not first_saved and seq>=15:
                    cv2.imwrite(str(output/'preview.png'),frame);first_saved=True
                summary.update(frames=seq,width=width,height=height,decode_fps=values[4],
                    battery=values[5],board_temperature_c=[values[6],values[7]],
                    video_bytes=int(values[8]),decode_errors=int(values[9]),
                    seconds_since_decoded_frame=max(0,now-values[1]),
                    telemetry_age_seconds=max(0,now-values[10]) if values[10] else None)
            elif now-started>10:
                raise RuntimeError('Stream acknowledged but no decoded frames after 10 seconds')
            if record_input is not None:
                pad = record_input.read()
                summary['gamepad_record_connected'] = pad.connected
                if record_button.tick(pad):
                    if recording is not None:
                        stop_recording()
                    else:
                        capture.toggle(last_image is not None and now-values[1]<2)
            key=cv2.waitKey(5)&255
            if key in (27,ord('q'),ord('Q')): break
            if key==32 and last_image is not None: start_recording()
            if key in (ord('r'),ord('R')):
                if recording is not None: stop_recording()
                else: capture.toggle(last_image is not None and now-values[1]<2)
            if key in (ord('s'),ord('S')) and last_image is not None:
                filename=output/datetime.now().strftime('snapshot_%H%M%S_%f.png')
                cv2.imwrite(str(filename),last_image);print('Saved '+str(filename),flush=True)
            if now-last_stats>=3:
                if bridge is not None: bridge.save()
                save_status();print(json.dumps({k:summary.get(k) for k in ('frames','decode_fps','battery','board_temperature_c','decode_errors','output')}),flush=True)
                last_stats=now
            if now-last_keepalive>=8:
                # Read-only keepalive; never arm/start motors or send RC input.
                cmd.send(encode_command('battery?'))
                summary['commands'].append(dict(command='battery?',purpose='read-only keepalive'))
                last_keepalive=now
    except Exception as exc:
        summary['error']=str(exc);print('ERROR: '+str(exc),flush=True)
    finally:
        stop_recording()
        capture.stop()
        if attempted_stream:
            try: summary['streamoff_acknowledged']=any(request('streamoff',1.5) for _ in range(2))
            except Exception as exc: summary['streamoff_error']=str(exc)
        stop.set()
        if worker.pid is not None:
            worker.join(3)
            if worker.is_alive(): worker.terminate();worker.join();summary['receiver_forced_termination']=True
        capture.finish()
        if bridge is not None:
            bridge.close()
            summary['rk_decode'] = bridge.latest()[2]
            if summary['rk_decode'].get('event') == 'error':
                summary.setdefault('error','RK media bridge: '+summary['rk_decode'].get('error','unknown'))
        summary.update(capture.snapshot())
        while not errors.empty(): summary.setdefault('receiver_errors',[]).append(errors.get())
        cmd.close();cv2.destroyAllWindows()
        summary['closed']=True;save_status()
        print(json.dumps(summary),flush=True)
    return 1 if summary.get('error') or summary.get('receiver_errors') else 0


if __name__=='__main__':
    mp.freeze_support()
    raise SystemExit(main())
