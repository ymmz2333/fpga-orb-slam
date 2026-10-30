"""Portable localization map packaging, validation and direct RK->Zynq upload."""
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import math

from .calibration import read, fingerprint
from .protocol import PROFILE, Kind, Packet, connect, receive

REQUIRED = {'camera_orb.csv', 'points.csv', 'representative_descriptors.bin',
            'keyframes.csv', 'observations.csv', 'observation_descriptors.bin', 'map.json'}
MAX_POINTS = 30000
MAX_KEYS = 1024
MAX_TOTAL = 64 * 1024 * 1024
FIELDS_CAMERA = ('fx', 'fy', 'cx', 'cy', 'd0', 'd1', 'd2', 'd3', 'd4')


def rows(path):
    with Path(path).open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def seal(folder, calibration, map_id):
    folder = Path(folder)
    camera_data = Path(calibration).read_bytes()
    if (read(camera_data)['width'], read(camera_data)['height']) != (960, 720):
        raise ValueError('Map needs the cropped working-image calibration')
    (folder / 'camera_orb.csv').write_bytes(camera_data)
    points, keys = rows(folder / 'points.csv'), rows(folder / 'keyframes.csv')
    # Keyframe intrinsics are float32 in ORB-SLAM3. Check that exact
    # representation before restoring the shared float64 calibration metadata.
    # This does not allow a different camera or another crop.
    camera = read(camera_data)
    for key in keys:
        for field in FIELDS_CAMERA:
            expected = camera[field]
            f32 = struct.unpack('<f', struct.pack('<f', expected))[0]
            actual = float(key[field])
            if not (math.isclose(actual, expected, rel_tol=0, abs_tol=1e-10) or
                    math.isclose(actual, f32, rel_tol=0, abs_tol=1e-10)):
                raise ValueError('Exported keyframe uses another camera: ' + field)
            key[field] = format(expected, '.17g')
    if keys:
        with (folder / 'keyframes.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(keys[0]))
            writer.writeheader()
            writer.writerows(keys)
    if not 1 <= len(points) <= MAX_POINTS or not 1 <= len(keys) <= MAX_KEYS:
        raise ValueError(f'Map has {len(points)} points / {len(keys)} keyframes; '
                         f'expected 1..{MAX_POINTS} points / 1..{MAX_KEYS} keyframes')
    meta = dict(format_version=1, map_id=int(map_id), points=len(points), keyframes=len(keys),
                calibration_sha256=fingerprint(camera_data), profile=PROFILE,
                coordinates='Original SLAM world; Twc camera-to-world; relative unmeasured scale',
                cpu_orb_calls=0, final_optimization_finished=True)
    (folder / 'map.json').write_text(json.dumps(meta, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    names=REQUIRED | ({'dense_environment.bin'} if (folder/'dense_environment.bin').is_file() else set())
    lines = [('%s %%s %%s %%d %%d %%d' % ('ORB60_MAP_V2' if len(names)>len(REQUIRED) else 'ORB60_MAP_V1')) %
             (fingerprint(camera_data), PROFILE, int(map_id), len(points), len(keys))]
    for name in sorted(names):
        data = (folder / name).read_bytes()
        lines.append('%s %d %s' % (hashlib.sha256(data).hexdigest(), len(data), name))
    manifest = ('\n'.join(lines) + '\n').encode('ascii')
    (folder / 'manifest.txt').write_bytes(manifest)
    validate(folder, camera_data)
    return hashlib.sha256(manifest).hexdigest()


def parse_manifest(data, expected_calibration):
    lines = data.decode('ascii').splitlines()
    head = lines[0].split() if lines else []
    if len(head) != 6 or head[0] not in ('ORB60_MAP_V1','ORB60_MAP_V2') or head[1:3] != [expected_calibration, PROFILE]:
        raise ValueError('Map profile/calibration mismatch')
    mid, points, keys = map(int, head[3:])
    if mid < 0 or not 1 <= points <= MAX_POINTS or not 1 <= keys <= MAX_KEYS:
        raise ValueError('Map capacity/identity invalid')
    names=REQUIRED | ({'dense_environment.bin'} if head[0]=='ORB60_MAP_V2' else set())
    files = {}
    for line in lines[1:]:
        digest, size, name = line.split()
        size = int(size)
        if (name not in names or name in files or len(digest) != 64 or
                any(c not in '0123456789abcdef' for c in digest) or not 0 <= size <= 32 * 1024 * 1024):
            raise ValueError('Invalid bounded map manifest entry')
        files[name] = (size, digest)
    if set(files) != names or sum(v[0] for v in files.values()) > MAX_TOTAL:
        raise ValueError('Incomplete or oversized map manifest')
    return mid, points, keys, files


def validate(folder, expected_camera):
    folder = Path(folder)
    mid, np_, nk, files = parse_manifest((folder / 'manifest.txt').read_bytes(), fingerprint(expected_camera))
    for name, (size, digest) in files.items():
        path = folder / name
        if path.is_symlink() or path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Map file checksum/size mismatch: ' + name)
    if (folder / 'camera_orb.csv').read_bytes() != expected_camera:
        raise ValueError('Camera bytes differ')
    if 'dense_environment.bin' in files:
        from .dense_environment import validate as validate_dense
        validate_dense(folder/'dense_environment.bin',folder/'points.csv',folder/'camera_orb.csv')
    points, keys, obs = rows(folder / 'points.csv'), rows(folder / 'keyframes.csv'), rows(folder / 'observations.csv')
    if (len(points), len(keys)) != (np_, nk):
        raise ValueError('Manifest counts differ from map')
    pids, kids = {int(p['point_id']) for p in points}, {int(k['keyframe_id']) for k in keys}
    if len(pids) != np_ or len(kids) != nk or min(pids) < 0 or min(kids) < 0:
        raise ValueError('Duplicate/invalid map IDs')
    if (folder / 'representative_descriptors.bin').stat().st_size != np_ * 32 or (folder / 'observation_descriptors.bin').stat().st_size != len(obs) * 32:
        raise ValueError('Map descriptor association length mismatch')
    import math
    camera = read(expected_camera)
    for p in points:
        if int(p['observations']) < 3 or not all(math.isfinite(float(p[k])) for k in ('x', 'y', 'z')):
            raise ValueError('Unreliable/nonfinite map point')
    for key in keys:
        for k in ('fx', 'fy', 'cx', 'cy', 'd0', 'd1', 'd2', 'd3', 'd4'):
            if not math.isclose(float(key[k]), camera[k], rel_tol=0, abs_tol=1e-8):
                raise ValueError('Keyframe calibration mismatch')
        pose = [float(key['twc_%d%d' % (r, c)]) for r in range(4) for c in range(4)]
        if not all(math.isfinite(v) for v in pose) or any(abs(pose[12+i]-v) > 1e-6 for i, v in enumerate((0, 0, 0, 1))):
            raise ValueError('Invalid keyframe pose')
        # Rotation must remain rigid; do not silently orthogonalize source data.
        for r in range(3):
            for c in range(3):
                if abs(sum(pose[i*4+r]*pose[i*4+c] for i in range(3)) - (r == c)) > 1e-5:
                    raise ValueError('Nonrigid keyframe pose')
    pairs = set()
    for i, o in enumerate(obs):
        pid, kid = int(o['point_id']), int(o['keyframe_id'])
        if pid not in pids or kid not in kids or int(o['descriptor_row']) != i or (pid, kid) in pairs:
            raise ValueError('Invalid observation association')
        pairs.add((pid, kid))
        if not 0 <= int(o['octave']) < 8 or not all(math.isfinite(float(o[k])) for k in ('u', 'v', 'raw_u', 'raw_v')):
            raise ValueError('Invalid observation pixels/octave')
    return dict(map_id=mid, points=np_, keyframes=nk, observations=len(obs),
                version=hashlib.sha256((folder / 'manifest.txt').read_bytes()).hexdigest())


def upload(folder, host, port=5603):
    folder = Path(folder)
    info = validate(folder, (folder / 'camera_orb.csv').read_bytes())
    with connect(host, port, 120) as sock:
        def transact(packet):
            sock.sendall(packet.encode())
            result = receive(sock)
            if result.kind == Kind.ERROR:
                raise RuntimeError(result.body.decode('utf-8', 'replace'))
            if result.kind != Kind.STATUS:
                raise ValueError('Invalid map transfer acknowledgment')
            return json.loads(result.body)
        transact(Packet(Kind.MAP_BEGIN, body=(folder / 'manifest.txt').read_bytes()))
        _,_,_,files=parse_manifest((folder/'manifest.txt').read_bytes(),fingerprint((folder/'camera_orb.csv').read_bytes()))
        for name in sorted(files):
            transact(Packet(Kind.MAP_FILE, body=name.encode('ascii') + b'\n' + (folder / name).read_bytes()))
        result = transact(Packet(Kind.MAP_COMMIT))
    return dict(info, installation=result)
