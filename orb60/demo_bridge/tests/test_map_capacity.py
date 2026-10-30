"""Synthetic count-boundary checks; no claim of board localization throughput."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from orb60.demo_bridge.map_bundle import (
    MAX_KEYS, MAX_POINTS, parse_manifest, rows, seal, validate,
)
from orb60.demo_bridge.calibration import fingerprint
from .offline_gate import OUT, bundle, write_rows


class MapCapacity(unittest.TestCase):
    def test_maximum_roundtrip_and_overflow_preserve_published_map(self):
        native = Path(os.environ.get('ORB60_CAPACITY_INSTALLER',
                         OUT/'capacity_1024_30000/native/zynq-map-install.exe'))
        self.assertTrue(native.is_file(), 'Build the capacity candidate first')
        with tempfile.TemporaryDirectory(dir=OUT) as temporary:
            root = Path(temporary)
            source = root/'map'
            camera = bundle(source)
            base = rows(source/'keyframes.csv')[0]
            keys = []
            for i in range(MAX_KEYS):
                key = dict(base, keyframe_id=i, slam_frame_id=i,
                           timestamp_ns=1000000000+i*33333333)
                keys.append(key)
            points = [dict(point_id=i+1, x=i*.001, y=0, z=3, observations=3)
                      for i in range(MAX_POINTS)]
            observations = []
            for i in range(MAX_POINTS):
                for shift in range(3):
                    observations.append(dict(keyframe_id=(i+shift)%MAX_KEYS,
                        point_id=i+1, u=400, v=300, raw_u=400, raw_v=300,
                        octave=0, descriptor_row=len(observations)))
            write_rows(source/'points.csv', points)
            write_rows(source/'keyframes.csv', keys)
            write_rows(source/'observations.csv', observations)
            (source/'representative_descriptors.bin').write_bytes(b'\x35'*32*MAX_POINTS)
            (source/'observation_descriptors.bin').write_bytes(b'\x35'*32*len(observations))
            version = seal(source, camera, 7)
            info = validate(source, camera.read_bytes())
            self.assertEqual((info['points'], info['keyframes']), (30000, 1024))
            store = root/'store'
            result = subprocess.run([native, store, camera, source, version],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = (store/'versions'/version/'map.zmap').read_bytes()
            self.assertEqual(struct.unpack_from('<II', saved, 92), (30000, 1024))
            # MapStore also checks byte-identical native save/load/save internally.
            pointer = (store/'current').read_bytes()
            manifest = (source/'manifest.txt').read_bytes()
            for points_count, key_count in ((30001, 1024), (30000, 1025)):
                lines = manifest.decode('ascii').splitlines()
                head = lines[0].split()
                head[4:6] = [str(points_count), str(key_count)]
                lines[0] = ' '.join(head)
                bad = ('\n'.join(lines)+'\n').encode('ascii')
                with self.assertRaises(ValueError):
                    parse_manifest(bad, fingerprint(camera.read_bytes()))
                (source/'manifest.txt').write_bytes(bad)
                rejected = subprocess.run([native, store, camera, source,
                    hashlib.sha256(bad).hexdigest()], capture_output=True, timeout=15)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual((store/'current').read_bytes(), pointer)
            (source/'manifest.txt').write_bytes(manifest)


if __name__ == '__main__':
    unittest.main()
