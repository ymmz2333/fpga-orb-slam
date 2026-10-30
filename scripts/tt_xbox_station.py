"""Windows Xbox/TT station. Default: DRY RUN, no UDP or ARP at all.

Three processes in live mode: GUI, decoder/telemetry, TT input/control adapter.
Only the control process owns UDP8889. No flight tests run automatically.
"""
import argparse
import ctypes
from ctypes import wintypes
from dataclasses import asdict
from datetime import datetime
import ipaddress
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import socket
import time

import cv2
import numpy as np

from tt_controller_core import (Controller, Health, Keys, Pad, SETUP, encode_command,
                                DEFAULT_RC_LIMIT, DEFAULT_SIGNS, DEFAULT_XY_EXPO, DEFAULT_CENTER_STOP_DELAY)
from tt_quorum_actions import QuorumFlightActions, DEFAULT_TAKEOFF_TIMEOUT
from tt_video_viewer import MAX_BYTES, bind_udp, receive_video, verify_peer
from tt_video_capture import CaptureControls
from tt_video_config import DEFAULT_BITRATE
from tt_record_button import NativePad, NativeState, RecordButton, drain_record_requests

WINDOW = 'TT XBOX - 3/5 ACK | H hover | L land | U resume'
CONTROL_PROFILE = 'tt-quorum3-linear30-stop1-delay2-20261004'


class WindowsInput:
    def __init__(self, index, gui_pid):
        self.index, self.gui_pid = index, gui_pid
        self.dll = ctypes.WinDLL('xinput1_4.dll')
        self.dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(NativeState)]
        self.dll.XInputGetState.restype = wintypes.DWORD
        self.user = ctypes.WinDLL('user32.dll')
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.GetForegroundWindow.argtypes = []
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD

    def read(self):
        raw = NativeState()
        connected = self.dll.XInputGetState(self.index, ctypes.byref(raw)) == 0
        p = raw.pad
        pad = Pad(connected, p.lx, p.ly, p.rx, p.ry, p.lt, p.rt, p.buttons)
        pid = wintypes.DWORD()
        hwnd = self.user.GetForegroundWindow()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        focused = bool(hwnd) and pid.value == self.gui_pid
        # Only three specific key levels are read. Do not use unreliable low-bit events.
        keys = Keys(*(bool(self.user.GetAsyncKeyState(ord(k)) & 0x8000) for k in 'UHL'))
        return pad, keys, focused


def latest_put(channel, value):
    try:
        channel.put_nowait(value)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(value)
        except queue.Full:
            pass


def read_meta(meta):
    lock = meta.get_lock()
    if not lock.acquire(timeout=.02):
        return None
    try:
        return list(meta)
    finally:
        lock.release()


def health_from_meta(values, now):
    if values is None or len(values) < 14:
        return Health()
    age = lambda timestamp: now - timestamp if timestamp > 0 else math.inf
    return Health(age(values[1]), age(values[10]), age(values[12]), age(values[13]),
                  values[11], values[5])


def sample_health(meta, gui_heartbeat):
    # Take every shared timestamp snapshot BEFORE the evaluation clock. A decoder
    # update between clock() and read_meta() used to create false negative ages.
    values = read_meta(meta)
    gui_timestamp = gui_heartbeat[0]
    now = time.perf_counter()
    return now, health_from_meta(values, now), now - gui_timestamp


def station_receiver(*args):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    receive_video(*args)


def control_worker(args, gui_pid, meta, gui_heartbeat, close, done, statuses, events,
                   record_requests=None):
    # Parent handles Ctrl+C by asking us to land, not by killing this process.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    engine = Controller(args.rc_limit, tuple(args.signs),
                        takeoff_timeout=args.takeoff_timeout, xy_expo=args.xy_expo,
                        center_brake=not args.no_center_brake,
                        center_stop_delay=getattr(args, 'center_stop_delay', DEFAULT_CENTER_STOP_DELAY))
    actions = QuorumFlightActions(takeoff_timeout=args.takeoff_timeout)
    cmd = None
    configured = False
    close_at = None
    result = dict(closed=False, real_network=args.live)
    loop_started = time.perf_counter()
    record_button = RecordButton()
    record_request_drops = 0

    def event(**row):
        row['t'] = time.perf_counter()
        try:
            events.put_nowait(row)
        except queue.Full:
            pass  # Diagnostics may drop; never block the control loop on disk/GUI.

    def send(value):
        permitted_takeoff = engine.mode == 'TAKING_OFF'
        encode_command(value, takeoff_enabled=permitted_takeoff,
                       motion_enabled=engine.mode == 'FLYING', rc_limit=args.rc_limit)
        packets = (actions.request(value, engine.takeoff_at if value == 'takeoff' else time.perf_counter())
                   if value in ('takeoff', 'land') else (value,))
        # stop: one plain packet, no response wait, numbered action or control lock.
        # Plain replies cannot fill numbered takeoff/land quorum slots.
        for packet in packets:
            payload = encode_command(packet, takeoff_enabled=permitted_takeoff,
                                     motion_enabled=engine.mode == 'FLYING', rc_limit=args.rc_limit)
            if cmd is not None:
                cmd.send(payload)
            event(kind='command' if args.live else 'simulated_command', value=packet,
                  logical_command=value)
            if not args.live and packet.startswith('Re'):
                actions.receive(packet.split(' ', 1)[0] + ' ok', time.perf_counter())

    try:
        inputs = WindowsInput(args.controller_index, gui_pid)
        if args.live:
            cmd = bind_udp(args.local_ip, args.interface, 8889)
            cmd.connect((args.drone_ip, 8889))
            cmd.setblocking(False)
            # Startup has no flight permission. No RC/motor/takeoff during configuration.
            for value in SETUP:
                if value.startswith('setbitrate '):
                    value = f'setbitrate {getattr(args,"bitrate",DEFAULT_BITRATE)}'
                if close.is_set():
                    return
                send(value)
                # TT TextClient.send_sync_msg defaults to 10 seconds (not EP Client).
                deadline = time.perf_counter() + 10
                acknowledged = False
                while time.perf_counter() < deadline and not close.is_set():
                    try:
                        reply = cmd.recv(4096).decode('ascii', 'replace').strip('\0\r\n ')
                        event(kind='setup_reply', value=value, reply=reply)
                        if reply == 'ok':
                            acknowledged = True
                            break
                        if reply.startswith(('error', 'unactive')):
                            break
                    except BlockingIOError:
                        pass
                    time.sleep(.02)
                if not acknowledged:
                    raise RuntimeError('No setup acknowledgement: ' + value)
            configured = True
        else:
            configured = True
        last_mode = None
        last_status = 0.
        next_tick = time.perf_counter()
        while True:
            actions.expire(time.perf_counter())
            if cmd is not None:
                # Count distinct copy IDs in one observed response group. Do not
                # consume late takeoff replies as a newer landing action.
                for _ in range(32):
                    try:
                        reply = cmd.recv(4096).decode('ascii', 'replace').strip('\0\r\n ')
                        matched = actions.receive(reply, time.perf_counter())
                        if matched is not None:
                            event(kind='action_reply', **matched)
                        else:
                            event(kind='uncorrelated_reply', reply=reply)
                    except BlockingIOError:
                        break
                    except OSError as exc:
                        event(kind='receive_failed', error=str(exc))
                        raise RuntimeError('TT command receive failed') from exc
            pad, keys, focused = inputs.read()
            if getattr(args, 'headless', False):
                # The headless input diagnostic never generates simulated flight actions.
                pad = Pad(pad.connected, pad.lx, pad.ly, pad.rx, pad.ry)
                keys = Keys()
            now, health, gui_age = sample_health(meta, gui_heartbeat)
            if not args.live:
                simulated_height = (75 if engine.possibly_airborne and engine.takeoff_at is not None
                                    and now - engine.takeoff_at > 1 else 0)
                if engine.mode == 'LANDING':
                    simulated_height = 0
                health = Health(0, 0, 0, 0, simulated_height, 80)
            closing = close.is_set()
            if record_button.tick(pad) and not closing:
                if args.live and record_requests is not None:
                    try:
                        record_requests.put_nowait('toggle')
                        event(kind='record_button',button='Y')
                    except queue.Full:
                        record_request_drops += 1
                        event(kind='record_request_dropped',button='Y')
                elif not args.live:
                    event(kind='simulated_record_button',button='Y')
            if closing and close_at is None:
                close_at = now
            commands = engine.tick(now, pad, keys, health, focused=focused,
                                   gui_age=gui_age, close=closing,
                                   takeoff_status=actions.state('takeoff'),
                                   land_status=actions.state('land'))
            for value in commands:
                try:
                    send(value)
                except OSError as exc:
                    event(kind='send_failed', value=value, error=str(exc))
                    raise RuntimeError('TT command send failed') from exc
            snapshot = engine.snapshot()
            snapshot.update(pad=asdict(pad), health=asdict(health), focused=focused,
                            dry_run=not args.live, t=now, configured=configured,
                            actions=actions.snapshot(), sdk_initialized=configured,
                            control_profile=CONTROL_PROFILE,record_request_drops=record_request_drops)
            snapshot['takeoff_remaining_s'] = (max(0., args.takeoff_timeout - (now - engine.takeoff_at))
                if engine.mode == 'TAKING_OFF' and engine.takeoff_at is not None else None)
            if engine.mode != last_mode:
                event(kind='transition', **snapshot)
                last_mode = engine.mode
            if now - last_status >= .1:
                latest_put(statuses, snapshot)
                last_status = now
            if closing:
                if not engine.possibly_airborne:
                    result['exit_status'] = 'SDK land completed or no takeoff requested; visually verify'
                    break
                if now - close_at >= 20:
                    result['error'] = 'Closing after 20s without SDK land completion. Visually check aircraft; no new command retries.'
                    break
            if args.seconds and now - loop_started >= args.seconds:
                close.set()
            next_tick += .05
            delay = next_tick - time.perf_counter()
            if delay < 0:
                next_tick = time.perf_counter()
            else:
                time.sleep(delay)
    except BaseException as exc:
        result['error'] = str(exc)
        event(kind='fatal_error', error=str(exc))
        # No hidden automatic flight commands on exceptions. Delivery/state unknown.
    finally:
        if cmd is not None:
            # On uncertain airborne exit, stop all keepalives; don't suppress firmware failsafe.
            if not engine.possibly_airborne:
                try:
                    send('streamoff')
                except OSError:
                    pass
            cmd.close()
        result.update(engine.snapshot(), closed=True, actions=actions.snapshot(),
                      control_profile=CONTROL_PROFILE)
        # Final evidence is written after all aircraft commands cease, never in the loop.
        if getattr(args, 'output', None):
            (Path(args.output) / 'controller_exit.json').write_text(
                json.dumps(result, indent=2), encoding='utf-8')
        event(kind='exit', **result)
        latest_put(statuses, result)
        done.set()
        # Never hang flight shutdown because the GUI stopped draining diagnostics.
        events.cancel_join_thread()
        statuses.cancel_join_thread()


def draw_panel(frame, status, dry_run):
    width = 960
    image = np.zeros((850, width, 3), np.uint8)
    if frame is not None:
        scale = min(width / frame.shape[1], 480 / frame.shape[0])
        preview = cv2.resize(frame, (round(frame.shape[1]*scale), round(frame.shape[0]*scale)))
        left = (width-preview.shape[1]) // 2
        image[:preview.shape[0], left:left+preview.shape[1]] = preview
    else:
        title = 'DRY RUN - NO NETWORK / NO REAL FLIGHT' if dry_run else 'Waiting for live video...'
        cv2.putText(image, title, (35, 180), cv2.FONT_HERSHEY_SIMPLEX, .85, (80, 220, 255), 2)
    mode = status.get('mode', 'STARTING')
    p, h = status.get('pad', {}), status.get('health', {})
    remaining = status.get('takeoff_remaining_s')
    wait_label = f'{remaining:.1f}s left' if remaining is not None else 'not waiting'
    lines = [
        ('DRY / SIMULATED' if dry_run else 'LIVE / REAL AIRCRAFT') + ' | TT 3/5 ACK | ' + mode
        + (' | STICKS ENABLED' if status.get('motion_enabled') else ' | RC IDLE'),
        status.get('reason', 'Initializing TT SDK command channel...'),
        f"Xbox: {'CONNECTED' if p.get('connected') else 'NOT CONNECTED'} | Window: {'FOCUSED' if status.get('focused') else 'NOT FOCUSED'}",
        f"LX {p.get('lx',0):6} LY {p.get('ly',0):6} RX {p.get('rx',0):6} RY {p.get('ry',0):6} | LT {p.get('lt',0):3} RT {p.get('rt',0):3} LB {bool(p.get('buttons',0)&256)} RB {bool(p.get('buttons',0)&512)}",
        f"RC a,b,c,d: {status.get('rc', [0,0,0,0])} | limit {status.get('rc_limit',DEFAULT_RC_LIMIT)} | signs {status.get('signs',list(DEFAULT_SIGNS))}",
        f"Height {h.get('height',math.nan):.0f} cm | Battery {h.get('battery',math.nan):.0f}% | video age {h.get('video_age',math.inf):.1f}s | state age {h.get('state_age',math.inf):.1f}s",
        'H HOVER | U resume after H | L LAND | ESC quit (requests land)',
        'LT+RT >=85% for 1s: TAKEOFF | LB+RB: LAND | no preflight U required',
        f"Takeoff 3/5: {wait_label} | deadline {status.get('takeoff_timeout',DEFAULT_TAKEOFF_TIMEOUT):g}s | XY expo {status.get('xy_expo',DEFAULT_XY_EXPO):g} | center stop {status.get('center_stop_delay',DEFAULT_CENTER_STOP_DELAY):g}s {'ON' if status.get('center_brake',True) else 'OFF'}",
        'ACK: ' + ' | '.join(f"{name}={value['status']} {value.get('success_count',0)}/5 OK (group {value.get('response_group')})"
                                for name, value in status.get('actions', {}).items()),
        'Xbox: background OK | Letters: foreground | Center stop resumes on new input',
        status.get('recording_label','R: record video (live only)')+' | Xbox Y: start/stop REC'
    ]
    for i, line in enumerate(lines):
        color = (70, 190, 255) if i in (0, 6, 7) else (225, 225, 225)
        if i == 11 and status.get('recording_directory'):
            color = (70,70,255)
        cv2.putText(image, line, (12, 510 + i * 27), cv2.FONT_HERSHEY_SIMPLEX, .52, color, 1)
    return image


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--local-ip'); parser.add_argument('--drone-ip')
    parser.add_argument('--interface', type=int); parser.add_argument('--expected-mac')
    parser.add_argument('--controller-index', type=int, default=0, choices=range(4))
    parser.add_argument('--rc-limit', type=int, default=DEFAULT_RC_LIMIT, choices=range(1, 101))
    parser.add_argument('--signs', type=int, nargs=4, choices=(-1, 1), default=DEFAULT_SIGNS)
    parser.add_argument('--takeoff-timeout', type=float, default=DEFAULT_TAKEOFF_TIMEOUT)
    parser.add_argument('--xy-expo', type=float, default=DEFAULT_XY_EXPO)
    parser.add_argument('--center-stop-delay', type=float, default=DEFAULT_CENTER_STOP_DELAY)
    parser.add_argument('--no-center-brake', action='store_true')
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--headless', action='store_true', help='Read-only dry run, no key control')
    parser.add_argument('--capture-kind', choices=('flight','handheld'), default='flight')
    parser.add_argument('--bitrate', type=int, choices=range(6), default=DEFAULT_BITRATE)
    parser.add_argument('--decoder', choices=('software','d3d11va'), default='software')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.seconds < 0 or (args.live and args.headless):
        parser.error('Nonnegative duration required; headless mode is DRY RUN ONLY')
    if not 1 <= args.takeoff_timeout <= 14 or not 1 <= args.xy_expo <= 3:
        parser.error('Takeoff timeout must be 1..14 seconds; XY exponent 1..3')
    if args.live:
        if not all((args.local_ip, args.drone_ip, args.interface, args.expected_mac)):
            parser.error('Use run_tt_xbox.ps1 -Live with the lab interface')
        subnet = ipaddress.ip_network(args.local_ip + '/24', strict=False)
        if ipaddress.ip_address(args.drone_ip) not in subnet or args.local_ip == args.drone_ip:
            parser.error('TT must be a distinct address on the selected lab /24')
        verify_peer(args.local_ip, args.drone_ip, args.expected_mac)
    root = Path(os.environ['FPGA_PROJECT_ROOT'])
    output = root / '.work' / 'tt-xbox' / datetime.now().strftime('%Y%m%dT%H%M%S_%f')
    output.mkdir(parents=True)
    args.output = str(output)
    print(('LIVE: aircraft must be on ground. ' if args.live else 'DRY RUN: no UDP sockets or ARP. ')
          + 'No automatic takeoff. Output: ' + str(output), flush=True)
    ctx = mp.get_context('spawn')
    meta = ctx.Array('d', 14)
    meta[5:8] = [-1, -1, -1]
    meta[11] = math.nan
    buffer = ctx.RawArray('B', MAX_BYTES)
    heartbeat = ctx.RawArray('d', [time.perf_counter()])
    close, done, rx_stop, ready = [ctx.Event() for _ in range(4)]
    errors, recording, statuses, events = ctx.Queue(), ctx.Queue(), ctx.Queue(2), ctx.Queue(1024)
    recording_status = ctx.Queue()
    record_requests = ctx.Queue(32)
    capture = CaptureControls(ctx,recording,recording_status,root/'recordings'/'tt',args.capture_kind,
                              dict(bitrate=args.bitrate,resolution='high',fps='high'))
    receiver = None
    controller = None
    status, frame, sequence = {}, None, 0
    window_open = not args.headless
    failure = None
    log = (output / 'events.jsonl').open('x', encoding='utf-8')
    last_status_write = 0.
    try:
        if not args.headless:
            cv2.setNumThreads(1)
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
            cv2.resizeWindow(WINDOW, 1100, 894)
            cv2.imshow(WINDOW, draw_panel(None, {}, not args.live))
            cv2.waitKey(1)
        if args.live:
            receiver = ctx.Process(target=station_receiver, args=(args.local_ip, args.drone_ip,
                args.interface, buffer, meta, ready, rx_stop, errors, recording,recording_status,
                args.decoder,None,str(output)), daemon=True)
            receiver.start()
            if not ready.wait(4) or rx_stop.is_set():
                raise RuntimeError('Video/telemetry sockets unavailable. Close other TT viewers.')
        controller = ctx.Process(target=control_worker, args=(args, 0 if args.headless else os.getpid(),
            meta, heartbeat, close, done, statuses, events,record_requests))
        controller.start()
        print('TT SDK: H hover | L land | U resume | LT+RT hold 1s takeoff | LB+RB land', flush=True)
        print('Xbox Y / keyboard R: start/stop video recording. Y works in background.',flush=True)
        while controller.is_alive():
            heartbeat[0] = time.perf_counter()
            capture.poll()
            try:
                while True:
                    status.update(statuses.get_nowait())
            except queue.Empty:
                pass
            if status.get('t') and not status.get('closed') and time.perf_counter() - status['t'] > 1:
                status['reason'] = 'CONTROL PROCESS STALE - inspect controller/aircraft'
            try:
                while True:
                    row = events.get_nowait()
                    log.write(json.dumps(row, allow_nan=True) + '\n')
                    if row['kind'] in ('transition', 'exit', 'fatal_error', 'send_failed'):
                        print(json.dumps(row, allow_nan=True), flush=True)
                    if row['kind'] in ('exit', 'fatal_error') and row.get('error'):
                        failure = row['error']
            except queue.Empty:
                pass
            if receiver is not None:
                if not receiver.is_alive() or rx_stop.is_set():
                    status['video_warning'] = 'Video/telemetry process exited; Xbox control remains independent'
                lock = meta.get_lock()
                if lock.acquire(timeout=.02):
                    try:
                        seq, width, height = int(meta[0]), int(meta[2]), int(meta[3])
                        if seq != sequence and width > 0 and height > 0:
                            frame = np.frombuffer(buffer, dtype=np.uint8)[:width*height*3].copy().reshape(height,width,3)
                            sequence = seq
                    finally:
                        lock.release()
            drain_record_requests(record_requests,capture,enabled=args.live and not close.is_set(),
                                  video_available=frame is not None and time.perf_counter()-meta[1]<2)
            if window_open:
                status.update(capture.snapshot(),recording_label=capture.label())
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    window_open = False
                    close.set()
                else:
                    cv2.imshow(WINDOW, draw_panel(frame, status, not args.live))
                    key = cv2.waitKey(5) & 255
                    if key == 27:
                        close.set()
                    elif key in (ord('r'),ord('R')) and args.live:
                        capture.toggle(frame is not None and time.perf_counter()-meta[1]<2)
            else:
                time.sleep(.03)
            if time.perf_counter() - last_status_write > 1:
                (output / 'status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
                log.flush()
                last_status_write = time.perf_counter()
        if controller.exitcode:
            failure = f'Controller exited unexpectedly ({controller.exitcode}); inspect aircraft immediately'
    except KeyboardInterrupt:
        print('Closing: requesting controlled landing; do not unplug network yet.', flush=True)
        close.set()
    except Exception as exc:
        failure = str(exc)
        close.set()
    finally:
        capture.stop()
        close.set()
        if controller is not None and controller.pid is not None:
            # Keep decoder/telemetry alive during shutdown. Never terminate the control worker.
            while controller.is_alive():
                controller.join(.25)
                try:
                    while True:
                        row = events.get_nowait()
                        log.write(json.dumps(row) + '\n')
                        if row['kind'] == 'exit':
                            status.update(row)
                            failure = row.get('error') or failure
                except queue.Empty:
                    pass
            try:
                while True:
                    status.update(statuses.get_nowait())
            except queue.Empty:
                pass
        rx_stop.set()
        if receiver is not None:
            if receiver.pid is not None:
                receiver.join(2)
                if receiver.is_alive():
                    receiver.terminate()
                    receiver.join()
        capture.finish()
        while True:
            try:
                failure = errors.get_nowait()
            except queue.Empty:
                break
        exit_file = output / 'controller_exit.json'
        if exit_file.exists():
            status.update(json.loads(exit_file.read_text(encoding='utf-8')))
        elif controller is not None and controller.pid is not None:
            failure = failure or 'Missing controller exit record; flight outcome unverified'
        failure = status.get('error') or failure
        status.update(application_closed=True, dry_run=not args.live, error=failure,
                      output=str(output), real_flight_verified=False)
        status.update(capture.snapshot(),recording_label=capture.label())
        (output / 'status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
        cv2.imwrite(str(output / 'panel.png'), draw_panel(frame, status, not args.live))
        log.close()
        if not args.headless:
            cv2.destroyAllWindows()
        print(json.dumps(status, indent=2), flush=True)
    return 1 if failure else 0


if __name__ == '__main__':
    mp.freeze_support()
    raise SystemExit(main())
