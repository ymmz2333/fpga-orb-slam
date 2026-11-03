"""KV260-owned saved-video mapping, RGB map handoff and native 7015 localization.

Run in the explicit DPU runtime. No hardware loading, CPU feature/depth fallback,
map reset or computer frame source. SSH credentials remain outside this module.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix('.part')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def csv_rows(path):
    with Path(path).open(newline='') as stream: return list(csv.DictReader(stream))


def network_snapshot(output):
    """Record actual interfaces/routes; this alone cannot prove a physical cable."""
    result={'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'monotonic_ns':time.monotonic_ns(),'scope':'Observed link state, not an assertion of physical topology'}
    for name,args in [('links',['link','show','dev','eth0']),('addresses',['address','show','dev','eth0']),
                      ('routes',['route','show']),('ipv6_routes',['-6','route','show']),
                      ('ipv6_neighbors',['-6','neigh','show','dev','eth0'])]:
        command=['ip','-j',*args]
        result[name]=json.loads(subprocess.check_output(command,text=True,timeout=8))
    for name in ('address','carrier','speed','duplex'):
        result[name]=Path('/sys/class/net/eth0',name).read_text().strip()
    save(output,result)


def check_configuration(config, connection):
    """Refuse accidental changes to the tested physical two-board boundary."""
    if type(connection.get('fixed_map_multiview',False)) is not bool:raise ValueError('Explicit boolean fixed-map matching selection required')
    expected = dict(decoder_mode='uncompressed', uncompressed_transport='file',
                    point_backend='pl', point_memory_backend='native-dpu',
                    mapper_wait_mode='published', motion_pose_policy='original')
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError('Local saved input and the explicit physical PL/DPU pipeline are required')
    if (config.get('profile') or config.get('tracking_trace') or
        config.get('depth_interval_ns') != 1000000000 or
        config.get('acceptance_profile') not in ('stable_map_5fps', 'stable_map_5fps_tail84')):
        raise ValueError('Unprofiled 1-second DPU selection and explicit stable-map acceptance required')
    if not config.get('gpu_only') or config.get('local_ba_neighbors') != 10:
        raise ValueError('Tested bounded mapper and Mali-only display configuration required')
    host = connection.get('host', '')
    if not re.fullmatch(r'fe80::[a-fA-F0-9:]+%[a-zA-Z0-9_-]+', host):
        raise ValueError('Explicit numeric link-local peer with interface required')
    if config.get('endpoint') != '[' + host + ']:5600':
        raise ValueError('Control peer and physical ORB endpoint differ')
    for key in ('frontend_release', 'localization_template', 'release_parent'):
        value = connection.get(key, '')
        if not re.fullmatch(r'/opt/orb-demo/[a-zA-Z0-9_-]+', value):
            raise ValueError('Explicit isolated /opt/orb-demo release path required: ' + key)
    for key in ('frontend_sha256', 'localizer_sha256', 'raw_sha256', 'index_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', connection.get(key, '')):
            raise ValueError('Pinned binary/input identity required: ' + key)
    if connection.get('localization_frames') != 2273:
        raise ValueError('This saved-video entry requires the verified 2273-frame native 7015 input')
    for key in ('raw', 'raw_index'):
        if not re.fullmatch(r'/opt/[a-zA-Z0-9_/.-]+', connection.get(key, '')) or '..' in PurePosixPath(connection[key]).parts:
            raise ValueError('Explicit native 7015 saved input path required')


def verify_current_platform(root, config, connection, boot_file='/proc/sys/kernel/random/boot_id'):
    """Reject pre-reboot proofs before opening any KV260 PL control registers."""
    root=Path(root);boot=Path(boot_file).read_text().strip()
    def path(value):
        p=Path(value);return p if p.is_absolute() else root/p
    receipt_path=path(connection['kv_deployment_receipt']);receipt=load(receipt_path)
    point=load(path(config['point_preflight']));dpu=load(path(config['preflight']))
    if (receipt.get('status')!='DPU_POINTS_LOADED' or receipt.get('boot_id')!=boot or
        receipt.get('memory_backend')!='native-dpu' or receipt.get('point_uio')!=config['point_uio'] or
        point.get('status')!='DPU_POINTS_BOARD_PREFLIGHT_PASS' or point.get('boot_id')!=boot or
        point.get('deployment_receipt_sha256')!=digest(receipt_path) or
        point.get('bitstream_sha256')!=receipt.get('bitstream_sha256') or
        dpu.get('status')!='PROFILE_MATCH' or dpu.get('driver')!='vivado' or dpu.get('boot_id')!=boot):
        raise ValueError('Current-boot DPU+point platform load and fresh execution checks required; no automatic loading')
    return dict(status='CURRENT_BOOT_PLATFORM_PROOFS_MATCH',boot_id=boot,receipt_sha256=digest(receipt_path),
                point_preflight_sha256=digest(path(config['point_preflight'])),dpu_preflight_sha256=digest(path(config['preflight'])))


def extract_evidence(archive, output, maximum_bytes=64 * 1024 * 1024):
    """Only owned, regular report files; never extract links or outside paths."""
    output = Path(output)
    output.mkdir(exist_ok=False)
    total = 0
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            relative = PurePosixPath(member.name)
            if member.isdir() and member.name in ('.', './'): continue
            if relative.is_absolute() or '..' in relative.parts or '\\' in member.name or not relative.parts:
                raise ValueError('Unsafe report archive path')
            target = output.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(output.resolve()): raise ValueError('Report path escaped output')
            if member.isdir(): target.mkdir(parents=True, exist_ok=True); continue
            total += member.size
            if not member.isfile() or total > maximum_bytes or member.size > 16 * 1024 * 1024:
                raise ValueError('Nonregular or oversized report archive entry')
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)


def verify_localization(folder, expected_version, expected_frames=2273):
    folder = Path(folder)
    if (folder / 'exit_code').read_text().strip() != '0': raise ValueError('Native localization failed')
    poses = csv_rows(folder / 'app/poses.part000000.csv')
    timings = csv_rows(folder / 'app/timing.part000000.csv')
    rendering = csv_rows(folder / 'app/render.part000000.csv')
    index = csv_rows(folder / 'input_index.csv')
    if not all(len(v) == expected_frames for v in (poses, timings, rendering, index)):
        raise ValueError('Native localization/report coverage is incomplete')
    for i, (pose, timing, render, original) in enumerate(zip(poses, timings, rendering, index)):
        if (int(pose['frame_id']) != i or int(timing['frame_id']) != i or int(render['frame_id']) != i or
            int(original['frame_index']) != i or pose['timestamp_ns'] != original['timestamp_ns'] or
            timing['timestamp_ns'] != pose['timestamp_ns'] or int(pose['pose_valid']) != int(timing['pose_valid']) or
            pose['map_version'] != expected_version or timing['map_version'] != expected_version):
            raise ValueError('Native localization frame/time/map identity mismatch')
        if pose['pose_valid'] not in ('0', '1'): raise ValueError('Invalid pose validity bit')
        values = [pose[k] for k in ('tx', 'ty', 'tz', 'r00', 'r01', 'r02', 'r10', 'r11', 'r12', 'r20', 'r21', 'r22')]
        if (pose['pose_valid'] == '1' and not all(math.isfinite(float(v)) for v in values)) or (pose['pose_valid'] == '0' and any(values)):
            raise ValueError('Invalid poses must be empty, valid poses must be finite')
    status = load(folder / 'app/status.json'); display = load(folder / 'app/display.json')
    if (not status.get('hardware_verified') or status.get('hardware_fault') or status.get('cpu_orb_calls') != 0 or
        display.get('submitted') != expected_frames or display.get('underruns') or display.get('axi_errors')):
        raise ValueError('Physical PL or HDMI verification failed')
    first = next((i for i, p in enumerate(poses) if int(p['pose_valid'])), None)
    valid = sum(int(p['pose_valid']) for p in poses)
    if first is None or valid / (len(poses) - first) < .98:
        raise ValueError('7015 fixed-map localization is below98% after initialization')
    before = (folder / 'map_before.txt').read_bytes(); after = (folder / 'map_after.txt').read_bytes()
    if before != after or before.decode().splitlines()[0] != expected_version:
        raise ValueError('Localizer changed its fixed map')
    begin, end = map(float, (folder / 'monotonic_bounds.txt').read_text().split())
    if end <= begin: raise ValueError('Invalid native timing bounds')
    builds = sum(int(r['background_builds']) for r in rendering)
    hits = sum(int(r['background_hits']) for r in rendering)
    if builds != 1 or hits != expected_frames - 1: raise ValueError('Fixed colored background was not reused for the whole recording')
    return dict(status='ACTUAL_7015_FIXED_MAP_COLOR_HDMI_PASS', frames=len(poses), valid=valid,
                valid_after_initialization=valid/(len(poses)-first), seconds=end-begin, fps=len(poses)/(end-begin),
                cpu_orb_calls=0, map_version=expected_version, map_unchanged=True, display=display,
                background_builds=builds, background_hits=hits)


class Board:
    def __init__(self, root, connection, output):
        self.root, self.connection, self.output = Path(root), connection, Path(output)
        key = self.path(connection['identity']); hosts = self.path(connection['known_hosts'])
        if not key.is_file() or not hosts.is_file(): raise ValueError('Provision the private board-to-board SSH identity and pinned host file first')
        self.command = ['ssh', '-i', str(key), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=+ssh-rsa',
                        '-o', 'PubkeyAcceptedAlgorithms=+ssh-rsa', '-o', 'ConnectTimeout=8',
                        '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                        '-o', 'UserKnownHostsFile=' + str(hosts), 'root@' + connection['host']]
        self.frontend = None; self.frontend_log = None

    def path(self, value):
        path = Path(value); return path if path.is_absolute() else self.root / path

    def run(self, script, name, timeout=120, stdin=None, stdout=None):
        with (self.output / (name + '.stderr.log')).open('wb') as error:
            if stdout is None:
                with (self.output / (name + '.stdout.log')).open('wb') as result:
                    completed = subprocess.run(self.command + [script], stdin=stdin, stdout=result, stderr=error, timeout=timeout)
            else:
                completed = subprocess.run(self.command + [script], stdin=stdin, stdout=stdout, stderr=error, timeout=timeout)
        if completed.returncode: raise RuntimeError('7015 command failed: ' + name)

    def preflight(self):
        c = self.connection
        script = '''set -eu
test ! -e /run/orb-demo.lock
test "$(cat /sys/class/uio/uio0/version)" = wc1
test "$(cat /sys/class/net/eth0/carrier)" = 1
cat /proc/sys/kernel/random/boot_id
cat /sys/class/net/eth0/address /sys/class/net/eth0/speed /sys/class/net/eth0/duplex
'''
        for directory, binary, expected in [(c['frontend_release'], 'orb60-server', c['frontend_sha256']),
                                             (c['localization_template'], 'zynq-demo', c['localizer_sha256'])]:
            script += '(cd ' + shlex.quote(directory) + ' && sha256sum -c SHA256SUMS >/dev/null)\n'
            script += 'test "$(sha256sum ' + shlex.quote(directory + '/bin/' + binary) + ' | cut -d " " -f 1)" = ' + expected + '\n'
        self.run(script, 'preflight')
        for name in ('raw', 'raw_index'):
            # Full source verification is startup work, never reported as steady FPS.
            expected = c['raw_sha256' if name == 'raw' else 'index_sha256']
            self.run('set -eu; test "$(sha256sum ' + shlex.quote(c[name]) + ' | cut -d " " -f 1)" = ' + expected,
                     'input_' + name, timeout=240)

    def start_frontend(self):
        from .install_camera_map_7015 import require_space
        require_space(self)
        script = shlex.quote(self.connection['frontend_release'] + '/run_orb_frontend.sh') + ' --stdin-control'
        self.frontend_log = (self.output / 'frontend.log').open('wb')
        self.frontend = subprocess.Popen(self.command + [script], stdin=subprocess.PIPE,
                                         stdout=self.frontend_log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.frontend.poll() is not None: raise RuntimeError('Physical ORB frontend stopped during startup')
            if b'ORB_FRONTEND_READY=physical\n' in (self.output / 'frontend.log').read_bytes(): return
            time.sleep(.1)
        raise TimeoutError('No physical ORB readiness receipt')

    def stop_frontend(self):
        child = self.frontend
        if child is None: return
        if child.poll() is not None: raise RuntimeError('Frontend stopped before controlled handoff')
        child.stdin.write(b'STOP\n'); child.stdin.flush(); child.stdin.close()
        result = child.wait(timeout=20)
        self.frontend_log.close(); self.frontend = None
        if result: raise RuntimeError('Frontend did not confirm its controlled stop')

    def cancel_frontend(self):
        if self.frontend is None: return
        child = self.frontend
        if child.poll() is None:
            child.stdin.close()  # EOF stops only this invocation's owned server.
            child.wait(timeout=20)
        self.frontend_log.close(); self.frontend = None

    def install(self, handoff):
        from orb60.demo_bridge.map_bundle import validate
        handoff = Path(handoff); proof = load(handoff / 'HANDOFF.json'); transfer = load(handoff / 'TRANSFER.json')
        camera = handoff / 'map/camera_orb.csv'; bundle = validate(handoff / 'map', camera.read_bytes())
        if proof['dense_display_points'] < 1 or bundle['version'] != transfer['expected_map_version']:
            raise ValueError('Sealed same-map colored environment required')
        archive = handoff / 'map_7015.tar.gz'
        if digest(archive) != transfer['sha256'] or archive.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Map transfer archive identity/capacity mismatch')
        c = self.connection; release = c['release_parent'] + '_' + self.output.name
        # output.name is checked at the public entry point, so all shell paths
        # below have the same bounded, reviewable isolated-release shape.
        script = 'set -eu; test ! -e /run/orb-demo.lock; test ! -e ' + shlex.quote(release)
        script += '; mkdir ' + shlex.quote(release) + '; cat > ' + shlex.quote(release + '/map.tar.gz')
        with archive.open('rb') as body: self.run(script, 'transfer', stdin=body)
        version = transfer['expected_map_version']
        script = '''set -eu
cd RELEASE
test "$(sha256sum map.tar.gz | cut -d ' ' -f 1)" = ARCHIVE_SHA
tar -xzf map.tar.gz
base=TEMPLATE
(cd "$base" && sha256sum -c SHA256SUMS >/dev/null)
mkdir bin
cp "$base/bin/zynq-demo" "$base/bin/zynq-map-install" bin/
cp "$base/run_recording_localization.sh" "$base/README_ZH.md" .
bin/zynq-map-install maps map/camera_orb.csv map VERSION
test "$(head -n 1 maps/current)" = VERSION
cmp maps/versions/VERSION/map.zmap maps/versions/VERSION/roundtrip.zmap
find bin map maps -type f | sort | xargs sha256sum >SHA256SUMS
sha256sum run_recording_localization.sh README_ZH.md >>SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null
sync
cat maps/current
'''
        for token, value in [('RELEASE', release), ('TEMPLATE', c['localization_template']),
                              ('ARCHIVE_SHA', transfer['sha256']), ('VERSION', version)]:
            script = script.replace(token, shlex.quote(value))
        self.run(script, 'install')
        return dict(release=release, version=version, dense_points=proof['dense_display_points'],
                    archive_sha256=transfer['sha256'], status='ACTUAL_NATIVE_7015_MAP_IMPORT_ROUNDTRIP_PASS')

    def localize(self, installed):
        release = installed['release']; c = self.connection
        self.run('KV260_REPLAY_RAW=' + shlex.quote(c['raw']) + ' KV260_REPLAY_INDEX=' + shlex.quote(c['raw_index']) +
                 ' ORB60_FIXED_MAP_MULTIVIEW='+('1' if c.get('fixed_map_multiview',False) else '0')+' ' + shlex.quote(release + '/run_recording_localization.sh'), 'localize', timeout=600)
        text = (self.output / 'localize.stdout.log').read_text()
        matches = re.findall(r'^RECORDED_COLOR_LOCALIZATION_RUN=(.+)$', text, flags=re.M)
        if len(matches) != 1 or not matches[0].startswith(release + '/runs/recording-'):
            raise ValueError('Missing native localization completion receipt')
        remote = matches[0]
        if not re.fullmatch(r'/opt/orb-demo/[a-zA-Z0-9_-]+/runs/recording-[a-zA-Z0-9_-]+', remote):
            raise ValueError('Invalid native localization receipt path')
        script = 'set -eu; cd ' + shlex.quote(release) + '; sha256sum -c SHA256SUMS >/dev/null; '
        script += 'cp maps/current ' + shlex.quote(remote + '/map_after.txt') + '; cp ' + shlex.quote(c['raw_index']) + ' ' + shlex.quote(remote + '/input_index.csv')
        script += '; tar -czf - -C ' + shlex.quote(remote) + ' .'
        archive = self.output / 'native_localization.tar.gz'
        with archive.open('wb') as stream: self.run(script, 'collect_localize', stdout=stream)
        extracted = self.output / 'native_localization'
        extract_evidence(archive, extracted)
        result = verify_localization(extracted, installed['version'], c['localization_frames'])
        if 'DENSE_ENVIRONMENT_POINTS=' + str(installed['dense_points']) not in (extracted / 'stdout.log').read_text():
            raise ValueError('Native HDMI program did not load the handed-off RGB environment')
        if c.get('fixed_map_multiview',False) and 'FIXED_MAP_MULTIVIEW=1' not in (extracted/'stdout.log').read_text():
            raise ValueError('Selected fixed-map view matching was not enabled by the native binary')
        result['fixed_map_multiview_selected']=c.get('fixed_map_multiview',False)
        return result


def run(config_path, connection_path, output, resume_mapping=None):
    if platform.machine() != 'aarch64' or not sys.platform.startswith('linux'):
        raise ValueError('This entry must execute on the actual KV260')
    config = load(config_path); connection = load(connection_path); check_configuration(config, connection)
    output = Path(output).resolve()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', output.name): raise ValueError('Use a bounded alphanumeric session name')
    output.mkdir(parents=True, exist_ok=False)
    root = Path(config['root']).resolve(); board = None
    report = dict(status='RUNNING', mode='COMPONENT_HANDOFF_FROM_ACCEPTED_MAP' if resume_mapping else 'FULL_TWO_BOARD_SAVED_VIDEO',
                  network_scope='CURRENT_NETWORK_UNVERIFIED_PHYSICAL_DIRECT_CABLE', computer_compute=False,
                  started_monotonic_ns=time.monotonic_ns(), source_sha256=digest(__file__),
                  config_sha256=digest(config_path), connection_sha256=digest(connection_path), stages={})
    (output / 'mapping_configuration.json').write_bytes(Path(config_path).read_bytes())
    (output / 'connection_configuration.json').write_bytes(Path(connection_path).read_bytes())
    snapshot=output/'source_snapshot';snapshot.mkdir()
    (snapshot/'two_board_session.py').write_bytes(Path(__file__).read_bytes())
    save(output / 'session.json', report)
    try:
        print('Checking the two-board platform and saved inputs...',flush=True)
        network_snapshot(output/'network_before.json')
        if resume_mapping is None:
            report['stages']['kv_platform']=verify_current_platform(root,config,connection)
        board = Board(root, connection, output); board.preflight()
        network_snapshot(output/'network_peer_connected.json')
        report['stages']['preflight'] = 'PASS'; save(output / 'session.json', report)
        if resume_mapping is None:
            print('Starting physical 7015 ORB and KV260 mapping / DPU / color fusion...',flush=True)
            board.start_frontend()
            mapping = output / 'mapping'
            with (output / 'mapping.log').open('wb') as log:
                completed = subprocess.run([sys.executable, '-m', 'orb60.kv260.run_network_system',
                                            '--config', str(Path(config_path).resolve()), '--output', str(mapping)],
                                           cwd=root / 'sources', stdout=log, stderr=subprocess.STDOUT, timeout=1500)
            if completed.returncode: raise RuntimeError('Whole-video physical mapping did not pass; no map handoff')
            board.stop_frontend()
        else:
            mapping = Path(resume_mapping).resolve()
        from .handoff_7015 import create
        print('Sealing the accepted map and its RGB environment...',flush=True)
        handoff = output / 'handoff'; camera = Path(config['camera'])
        if not camera.is_absolute(): camera = root / camera
        sealed = create(mapping, camera, handoff, include_dense=True)
        report['stages']['mapping'] = sealed['source']; save(output / 'session.json', report)
        print('Transferring the map and performing native 7015 import...',flush=True)
        installed = board.install(handoff); report['stages']['native_import'] = installed; save(output / 'session.json', report)
        print('Running standalone 7015 localization and fixed-view color HDMI...',flush=True)
        report['stages']['localization'] = board.localize(installed)
        report['status'] = 'ACTUAL_TWO_BOARD_SAVED_VIDEO_CHAIN_PASS' if resume_mapping is None else 'ACTUAL_MAP_HANDOFF_LOCALIZATION_COMPONENT_PASS'
    except BaseException as error:
        report.update(status='FAILED', error=repr(error)); raise
    finally:
        if board is not None:
            try: board.cancel_frontend()
            except BaseException as error:
                report.update(status='FAILED', cleanup_error=repr(error),
                              owned_frontend_client_pid=board.frontend.pid if board.frontend is not None else None,
                              cleanup_complete=False)
        try: network_snapshot(output/'network_after.json')
        except Exception as error: report['network_evidence_error']=repr(error)
        report['finished_monotonic_ns'] = time.monotonic_ns(); save(output / 'session.json', report)
    print(json.dumps(dict(status=report['status'], network_scope=report['network_scope'], output=str(output))), flush=True)
    return 0 if report['status'].endswith('_PASS') else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', dest='config_path', type=Path, required=True); parser.add_argument('--connection', dest='connection_path', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-mapping', type=Path, help='Explicit handoff-only component gate; never claims a new full mapping run')
    return run(**vars(parser.parse_args(argv)))


if __name__ == '__main__': raise SystemExit(main())
