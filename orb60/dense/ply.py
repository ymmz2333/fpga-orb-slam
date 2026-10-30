"""Binary RGB PLY, original SLAM world axes, with strict bounded loading."""
from pathlib import Path
import numpy as np

VERTEX = np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),('red','u1'),('green','u1'),('blue','u1')])


def write_ply(path, xyz, rgb):
    xyz, rgb = np.asarray(xyz), np.asarray(rgb)
    if xyz.shape != rgb.shape or xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("Invalid colored points")
    data = np.empty(len(xyz), VERTEX)
    for i, name in enumerate(('x','y','z')):
        data[name] = xyz[:, i]
    for i, name in enumerate(('red','green','blue')):
        data[name] = rgb[:, i]
    path = Path(path)
    tmp = path.with_suffix('.ply.part')
    with tmp.open('wb') as f:
        header = ('ply\nformat binary_little_endian 1.0\ncomment relative monocular SLAM world axes\n'
                  'element vertex %d\nproperty float x\nproperty float y\nproperty float z\n'
                  'property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n') % len(data)
        f.write(header.encode('ascii'))
        data.tofile(f)
    tmp.replace(path)


def read_ply(path, maximum=2000000):
    with Path(path).open('rb') as f:
        lines = []
        for _ in range(40):
            line = f.readline(256)
            if not line.endswith(b'\n'):
                raise ValueError('Invalid PLY header')
            lines.append(line.decode('ascii').strip())
            if lines[-1] == 'end_header':
                break
        else:
            raise ValueError('Oversized PLY header')
        if lines[:2] != ['ply','format binary_little_endian 1.0']:
            raise ValueError('Expected binary colored dense-result PLY')
        props = [x for x in lines if x.startswith('property ')]
        if props != ['property float '+x for x in ['x','y','z']] + ['property uchar '+x for x in ['red','green','blue']]:
            raise ValueError('Unsupported PLY properties')
        counts = [int(x.split()[-1]) for x in lines if x.startswith('element vertex ')]
        if len(counts) != 1 or not 0 <= counts[0] <= maximum:
            raise ValueError('PLY count exceeds configured capacity')
        data = np.fromfile(f, dtype=VERTEX, count=counts[0])
        if len(data) != counts[0] or f.read(1):
            raise ValueError('PLY payload length mismatch')
    xyz = np.column_stack([data[x] for x in ['x','y','z']])
    rgb = np.column_stack([data[x] for x in ['red','green','blue']])
    if not np.isfinite(xyz).all():
        raise ValueError('Nonfinite PLY coordinates')
    return xyz, rgb
