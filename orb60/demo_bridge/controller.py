"""RK-side orchestration. Video/features/map data go directly between the boards."""
import argparse
from collections import deque
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import struct
import signal
import threading
import time

from .calibration import fingerprint
from .map_bundle import seal, upload, MAX_KEYS, MAX_POINTS
from .protocol import command


class Controller:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.child = None
        self.reader = None
        self.ready = threading.Event()
        self.final_map_ready = threading.Event()
        self.busy = False
        self.state = 'IDLE'
        self.error = ''
        self.run = None
        self.last_action = None
        self.recent = deque(maxlen=12)
        self.zynq = {}
        self.cancelled = threading.Event()
        self.dense = None
        self.capacity_warning = ''

    def zcommand(self, action):
        return command(self.config['zynq_host'], self.config.get('control_port', 5602), action)

    def status(self):
        with self.lock:
            if self.child and self.child.poll() is not None and self.state == 'MAPPING' and not self.busy:
                self.state = 'ERROR'
                self.error = 'RK tracking process exited unexpectedly; no map activated'
                try:
                    self.zcommand('stop')
                except Exception:
                    pass
            stage={}
            if self.run and self.state in ('FINALIZING','INSTALLING','ERROR'):
                path=self.run/'tracking/handover_stage.json'
                if path.is_file():
                    try:stage=json.loads(path.read_text())
                    except (OSError,ValueError):pass
            return dict(state=self.state, error=self.error, busy=self.busy, zynq=self.zynq,handover_stage=stage,
                        run=str(self.run) if self.run else None, action=self.last_action,
                        recent=list(self.recent), viewer_port=self.config.get('viewer_port', 18765),
                        dense_enabled=bool(self.config.get('dense_enabled')),
                        zynq_host=self.config.get('zynq_host',''),
                        capacity_warning=self.capacity_warning,
                        receiver_returncode=self.child.poll() if self.child else None,
                        dense_port=self.config.get('dense_port',18786),
                        dense=self.dense.status() if self.dense else None)

    def refresh(self):
        while True:
            try:
                status = self.zcommand('status')
                with self.lock:
                    self.zynq = status
                    if status['mode'] == 'ERROR' and self.state in ('MAPPING', 'FINALIZING', 'INSTALLING'):
                        self.state, self.error = 'ERROR', status.get('error', 'Zynq processing stopped')
                    if self.state in ('LOCAL', 'LOCAL_RELOCALIZING') and status['mode'] == 'LOCAL':
                        self.state = 'LOCAL' if status['ready_to_disconnect'] else 'LOCAL_RELOCALIZING'
                    if self.state == 'IDLE' and status['mode'] == 'LOCAL':
                        pointer=Path(self.config['runs']).parent/'last_handover.json'
                        if pointer.is_file():
                            try:
                                saved=json.loads(pointer.read_text());run=Path(saved['run']).resolve();base=Path(self.config['runs']).resolve()
                                import hashlib
                                manifest=run/'tracking/map_for_zynq/manifest.txt'
                                if base in run.parents and saved['version']==status['map_version'] and hashlib.sha256(manifest.read_bytes()).hexdigest()==saved['version']:
                                    self.run=run
                            except (OSError,ValueError,KeyError):pass
                        self.state = 'LOCAL' if status['ready_to_disconnect'] else 'LOCAL_RELOCALIZING'
                if self.run and self.state == 'MAPPING':
                    snapshot=self.run/'telemetry/latest.orbv'
                    if snapshot.is_file():
                        with snapshot.open('rb') as stream:header=stream.read(32)
                        if len(header)==32 and header[:8]==b'ORBVIZ01':
                            _,_,_,_,points,keys,_=struct.unpack('<8s6I',header)
                            if keys>=MAX_KEYS*9//10 or points>=MAX_POINTS*9//10:
                                self.capacity_warning=('当前显示快照含 %d 个关键帧、%d 个地图点；Zynq 导出上限为 %d / %d，'
                                                       '接近或超过容量，请尽快结束建图。最终以导出检查为准。')%(keys,points,MAX_KEYS,MAX_POINTS)
                            else:
                                self.capacity_warning=''
                    if self.dense and self.dense.error:
                        raise RuntimeError('Live NPU/color processing failed: '+self.dense.error)
                    telemetry_status=self.run/'telemetry/status.json'
                    if telemetry_status.is_file() and json.loads(telemetry_status.read_text()).get('state')=='ERROR':
                        self.zcommand('abort')
                        self.state,self.error='ERROR','Current RK visualization failed; mapping stopped'
                        self._stop_child()
            except Exception as exc:
                with self.lock:
                    self.zynq = dict(reachable=False, error=str(exc))
                    # An unplug after handover is expected. It cannot turn a
                    # prior failure into a successful local tracking claim.
                    if self.state == 'MAPPING':
                        self.state, self.error = 'ERROR', 'Zynq disconnected during mapping: ' + str(exc)
                        try:self.zcommand('abort')
                        except Exception:pass
                        self._stop_child()
            time.sleep(1)

    def _log_reader(self, stream, logger):
        for line in stream:
            logger.info(line.rstrip())
            if 'BRIDGE_RECEIVER_READY' in line:
                self.ready.set()
            if 'BRIDGE_FINAL_MAP_READY' in line:
                self.final_map_ready.set()
            with self.lock:
                self.recent.append(line.rstrip()[:400])
        stream.close()

    def _start(self):
        if self.child and self.child.poll() is None:
            if self.state == 'MAPPING':
                return
            raise RuntimeError('Previous mapping process still owns its session')
        status = self.zcommand('status')
        expected = fingerprint(Path(self.config['camera']).read_bytes())
        if not status['hardware_verified'] or status['hardware_fault'] or status['calibration_sha256'] != expected:
            raise RuntimeError('Physical FPGA preflight or calibration mismatch')
        if status['mode'] in ('STOPPED','ERROR'):
            self.zcommand('prepare')
        self.run = Path(self.config['runs']) / datetime.datetime.now(datetime.timezone.utc).strftime('demo_%Y%m%dT%H%M%S_%fZ')
        self.run.mkdir(parents=True, exist_ok=False)
        self.capacity_warning=''
        self.ready.clear()
        self.final_map_ready.clear()
        logger = logging.getLogger(str(self.run))
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(self.run / 'tracking.log', maxBytes=1024*1024, backupCount=3)
        logger.addHandler(handler)
        # Atlas PreSave is incompatible with this custom runtime. Preserve a
        # complete raw CSV/descriptor backup inside ExportBridgeMap instead.
        camera_text=Path(self.config['rk_camera']).read_text()
        camera_text='\n'.join(line for line in camera_text.splitlines() if not line.strip().startswith('System.SaveAtlasToFile:'))
        saved_camera=self.run/'camera_for_mapping.yaml'
        saved_camera.write_text(camera_text+'\nSystem.SaveAtlasToFile: ""\n')
        args = [self.config['executable'], self.config['vocabulary'], str(saved_camera), self.config['camera'],
                self.config['zynq_host'], str(self.config.get('stream_port', 5601)), str(self.run / 'tracking'), str(self.run / 'telemetry')]
        env=None
        if self.config.get('dense_enabled'):
            import os
            folder=self.run/'dense/color_poses';folder.mkdir(parents=True)
            env=os.environ.copy();env['ORB60_BRIDGE_COLOR_POSES']=str(folder)
        self.child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,cwd=self.run)
        self.reader = threading.Thread(target=self._log_reader, args=(self.child.stdout, logger), daemon=True)
        self.reader.start()
        deadline=time.monotonic()+120
        while not self.ready.wait(.2):
            if self.cancelled.is_set() or self.child.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('RK receiver startup stopped/failed; see bounded tracking log')
        if self.cancelled.is_set() or self.child.poll() is not None:
            raise RuntimeError('RK receiver stopped before start')
        if self.config.get('dense_enabled'):
            from .dense_camera import DenseCamera
            self.dense=DenseCamera(self.config,self.run)
        deadline=time.monotonic()+3
        while not self.zcommand('status').get('stream_connected',True):
            if self.child.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('RK receiver handshake was not acknowledged by Zynq')
            time.sleep(.02)
        self.zynq = self.zcommand('start')
        self.state, self.error = 'MAPPING', ''
        # Separate display relay reads only this run. It does not process SLAM.
        self._start_relay(self.run / 'telemetry')

    def _start_relay(self, telemetry):
        from .telemetry import Relay
        if hasattr(self, 'relay'):
            self.relay.close()
        self.relay = Relay(telemetry, self.config.get('viewer_port', 18765))
        self.relay.start()

    def _finalize(self):
        if self.state in ('LOCAL', 'LOCAL_RELOCALIZING'):
            return
        if not self.child or self.state != 'MAPPING':
            raise RuntimeError('No current mapping session')
        self.zynq = self.zcommand('finalize')
        self.state = 'FINALIZING'
        if self.dense:self.dense.close();self.dense=None
        try:
            rc=self.child.wait(timeout=360)
        except subprocess.TimeoutExpired:
            (self.run/'handover_failure.json').write_text(json.dumps(dict(stage='WAIT_RECEIVER_EXIT',error='receiver did not exit within 360 seconds'),indent=2)+'\n')
            raise
        if self.reader:self.reader.join(timeout=2)
        stage_path=self.run/'tracking/handover_stage.json'
        stage=json.loads(stage_path.read_text()) if stage_path.exists() else dict(stage='UNKNOWN_BEFORE_STAGE_INSTRUMENTATION')
        result=dict(returncode=rc,signal=signal.Signals(-rc).name if rc<0 else None,stage=stage,recent=list(self.recent))
        (self.run/'handover_receiver_exit.json').write_text(json.dumps(result,indent=2)+'\n')
        if rc != 0 or not self.final_map_ready.wait(2):
            detail=next((line for line in reversed(self.recent) if 'BRIDGE_RK_FAILED:' in line),'')
            raise RuntimeError('RK shutdown/export failed rc=%s signal=%s stage=%s; old map preserved; %s'%(rc,result['signal'],stage['stage'],detail))
        if hasattr(self,'relay'):self.relay.close()
        from .export_map import prepare
        source = self.run / 'tracking/map'
        folder = self.run / 'tracking/map_for_zynq'
        prepare(source, folder)
        mid = int((source / 'map_id.txt').read_text())
        if self.cancelled.is_set():raise RuntimeError('Handover cancelled')
        self._attach_sources(folder)
        if self.config.get('dense_enabled'):
            from .finalize_dense import build as finalize_dense
            finalize_dense(self.run,folder,self.config['camera'])
        version = seal(folder, self.config['camera'], mid)
        self.state = 'INSTALLING'
        if self.cancelled.is_set():raise RuntimeError('Handover cancelled')
        receipt = upload(folder, self.config['zynq_host'], self.config.get('map_port', 5603))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.cancelled.is_set():raise RuntimeError('Handover cancelled')
            self.zynq = self.zcommand('status')
            if self.zynq['mode'] == 'ERROR':
                raise RuntimeError(self.zynq.get('error', 'Local activation failed'))
            if self.zynq['mode'] == 'LOCAL' and self.zynq['map_version'] == version:
                self.state = 'LOCAL' if self.zynq['ready_to_disconnect'] else 'LOCAL_RELOCALIZING'
                (self.run / 'handover.json').write_text(json.dumps(dict(version=version, receipt=receipt, zynq=self.zynq), indent=2) + '\n')
                pointer=Path(self.config['runs']).parent/'last_handover.json';part=pointer.with_suffix('.part')
                part.write_text(json.dumps(dict(run=str(self.run),version=version))+'\n');part.replace(pointer)
                return
            time.sleep(.2)
        raise RuntimeError('Native map activation not acknowledged; do not unplug yet')

    def _attach_sources(self, folder):
        import csv
        from .map_bundle import rows
        bystamp = {}
        for row in rows(self.run / 'tracking/frames.csv'):
            stamp = int(row['slam_timestamp_ns'])
            if stamp in bystamp:
                raise ValueError('Ambiguous SLAM timestamps')
            bystamp[stamp] = row
        keys = rows(folder / 'keyframes.csv')
        for key in keys:
            source = bystamp[int(key['timestamp_ns'])]
            key['timestamp_ns'] = source['timestamp_ns']
            key['source_frame_id'] = source['source_frame_id']
        with (folder / 'keyframes.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(keys[0]))
            writer.writeheader()
            writer.writerows(keys)

    def _stop_child(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=12)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)
        if self.dense:self.dense.close();self.dense=None
        if hasattr(self, 'relay'):
            self.relay.close()

    def action(self, action):
        if action not in ('start_mapping', 'finalize_and_localize', 'relocalize', 'stop'):
            raise ValueError('Unknown operation')
        with self.lock:
            if self.busy:
                if action=='stop':
                    self.cancelled.set()
                    def stop_transition():
                        try:
                            self.zynq=self.zcommand('stop')
                            self._stop_child()
                            self.state,self.error='STOPPED',''
                        except Exception as exc:
                            self._stop_child()
                            self.state,self.error='ERROR','Stop not acknowledged by Zynq: '+str(exc)
                    threading.Thread(target=stop_transition,daemon=True).start()
                    return self.status()
                if self.last_action == action:
                    return self.status()
                raise RuntimeError('Another transition is in progress')
            self.busy, self.last_action = True, action
            self.cancelled.clear()
        def work():
            try:
                if action == 'start_mapping':
                    self._start()
                elif action == 'finalize_and_localize':
                    self._finalize()
                elif action == 'relocalize':
                    self.zynq = self.zcommand('relocalize')
                    self.state = 'LOCAL_RELOCALIZING'
                    self.error = ''
                else:
                    self.zynq = self.zcommand('stop')
                    self._stop_child()
                    self.state = 'STOPPED'
            except Exception as exc:
                if not self.cancelled.is_set():self.state,self.error='ERROR',str(exc)
                self._stop_child()
                try:
                    if not self.cancelled.is_set() and self.zcommand('status')['mode'] in ('MAPPING','FINALIZING','INSTALLING'):
                        self.zcommand('abort')
                except Exception:
                    pass
            finally:
                with self.lock:
                    self.busy = False
        threading.Thread(target=work, daemon=True).start()
        return self.status()


def serve(controller, host, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/status':
                self.send_error(404)
                return
            self.reply(controller.status())

        def do_POST(self):
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if self.path != '/command' or not 1 <= n <= 1024:
                    raise ValueError('Invalid control request')
                request = json.loads(self.rfile.read(n))
                self.reply(controller.action(request['action']), 202)
            except (ValueError, KeyError, RuntimeError) as exc:
                self.reply(dict(error=str(exc)), 409)

        def reply(self, value, code=200):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=controller.refresh, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        controller._stop_child()
        server.server_close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--bind', default='0.0.0.0')
    p.add_argument('--port', type=int, default=5610)
    a = p.parse_args()
    config = json.loads(a.config.read_text())
    keys=['camera', 'rk_camera', 'executable', 'vocabulary', 'runs']
    if config.get('dense_enabled'):keys+=['depth_worker','depth_model','npu_acceptance']
    for key in keys:
        value = Path(config[key]).expanduser()
        config[key] = str(value if value.is_absolute() else (a.config.parent / value).resolve())
    serve(Controller(config), a.bind, a.port)
