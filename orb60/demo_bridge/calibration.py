"""One canonical calibration for source pixels, PL working pixels and RK SLAM."""
import csv
import hashlib
import io
import math
from pathlib import Path

FIELDS = 'width,height,fx,fy,cx,cy,d0,d1,d2,d3,d4'.split(',')


def read(data):
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    if len(rows) != 1 or set(rows[0]) != set(FIELDS):
        raise ValueError('Expected one full camera calibration')
    result = {k: float(rows[0][k]) for k in FIELDS}
    if not all(math.isfinite(v) for v in result.values()) or min(result['fx'], result['fy']) <= 0:
        raise ValueError('Invalid calibration')
    if any(result[k] != int(result[k]) for k in ('width', 'height')):
        raise ValueError('Nonintegral image dimensions')
    return result


def encode(camera):
    return (','.join(FIELDS) + '\n' + ','.join(str(int(camera[k])) if k in ('width', 'height')
            else format(camera[k], '.17g') for k in FIELDS) + '\n').encode('ascii')


def cropped(source):
    if (source['width'], source['height']) != (1280, 720):
        raise ValueError('This release requires 1280x720 source and centered 960x720 crop')
    return dict(source, width=960, height=720, cx=source['cx'] - 160)


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def generate(source, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    camera = cropped(read(Path(source).read_bytes()))
    data = encode(camera)
    (output / 'camera_orb.csv').write_bytes(data)
    yaml = ['%YAML:1.0', 'Camera.type: "PinHole"']
    for key in ('fx', 'fy', 'cx', 'cy'):
        yaml.append('Camera.' + key + ': ' + format(camera[key], '.17g'))
    for key, index in [('k1', 0), ('k2', 1), ('p1', 2), ('p2', 3), ('k3', 4)]:
        yaml.append('Camera.' + key + ': ' + format(camera['d' + str(index)], '.17g'))
    yaml += ['Camera.width: 960', 'Camera.height: 720', 'Camera.fps: 30.0', 'Camera.RGB: 0',
             'ORBextractor.nFeatures: 1000', 'ORBextractor.scaleFactor: 1.2', 'ORBextractor.nLevels: 8',
             'ORBextractor.iniThFAST: 20', 'ORBextractor.minThFAST: 7',
             'Viewer.KeyFrameSize: 0.05', 'Viewer.KeyFrameLineWidth: 1.0', 'Viewer.GraphLineWidth: 0.9',
             'Viewer.PointSize: 2.0', 'Viewer.CameraSize: 0.08', 'Viewer.CameraLineWidth: 3.0',
             'Viewer.ViewpointX: 0.0', 'Viewer.ViewpointY: -0.7', 'Viewer.ViewpointZ: -1.8', 'Viewer.ViewpointF: 500.0']
    (output / 'camera_rk.yaml').write_text('\n'.join(yaml) + '\n', encoding='ascii')
    return fingerprint(data)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, default=Path(__file__).parent / 'config/camera_source.csv')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(generate(a.source, a.output))
