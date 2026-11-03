"""Read the same pinhole calibration schema as the retained ORB-SLAM3 build."""
from pathlib import Path
import cv2
from orb60.demo_bridge.calibration import read, encode, FIELDS


def from_yaml(path):
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise ValueError('Cannot open SLAM camera YAML')
    try:
        version = storage.getNode('File.version')
        modern = not version.empty() and version.string() == '1.0'
        prefix = 'Camera1.' if modern else 'Camera.'
        kind = storage.getNode('Camera.type')
        if not kind.empty() and kind.string() != 'PinHole':
            raise ValueError('KV260 adapter requires pinhole calibration')
        def number(name, optional=False):
            node = storage.getNode(name)
            if node.empty():
                if optional:return 0.0
                raise ValueError('Missing SLAM calibration field: ' + name)
            return node.real()
        values = {k:number('Camera.'+k) for k in ('width','height')}
        values.update({k:number(prefix+k) for k in ('fx','fy','cx','cy')})
        values.update({'d'+str(i):number(prefix+k, optional=(k=='k3'))
                       for i,k in enumerate(('k1','k2','p1','p2','k3'))})
        if (values['width'],values['height']) != (960,720):
            raise ValueError('SLAM working-image dimensions must be 960x720')
        # encode gives integer dimensions; read rejects zero focal/NaN/Inf.
        data = encode(values)
        read(data)
        return data
    finally:
        storage.release()


def validate_pair(camera, yaml):
    actual = read(Path(camera).read_bytes())
    expected = read(from_yaml(yaml))
    if any(actual[k] != expected[k] for k in FIELDS):
        raise ValueError('Camera CSV and SLAM YAML differ; refusing inconsistent geometry')
    return actual
