import hashlib
from pathlib import Path
import struct,subprocess,tempfile,unittest,zlib
import numpy as np
from orb60.demo_bridge.dense_environment import write,validate
from orb60.demo_bridge.map_bundle import seal,validate as validate_map
from .offline_gate import bundle,OUT


class DenseEnvironment(unittest.TestCase):
    def test_version2_native_roundtrip_and_corruption_preserves_old_map(self):
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            root=Path(temp);folder=root/'map';camera=bundle(folder)
            xyz=np.array([[.1,.2,2],[.3,.4,3]],np.float32);rgb=np.array([[1,2,3],[7,8,9]],np.uint8)
            write(folder/'dense_environment.bin',xyz,rgb,folder/'points.csv',camera)
            self.assertEqual(validate(folder/'dense_environment.bin',folder/'points.csv',camera),2)
            version=seal(folder,camera,7);self.assertTrue((folder/'manifest.txt').read_text().startswith('ORB60_MAP_V2 '))
            exe=OUT/'native_20261026/zynq-map-install.exe';store=root/'store'
            result=subprocess.run([exe,store,camera,folder,version],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);pointer=(store/'current').read_bytes()
            raw=bytearray((folder/'dense_environment.bin').read_bytes());raw[-1]^=1
            (folder/'dense_environment.bin').write_bytes(raw)
            with self.assertRaises(ValueError):validate_map(folder,camera.read_bytes())
            result=subprocess.run([exe,store,camera,folder,version],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertEqual(pointer,(store/'current').read_bytes())

    def test_wrong_sparse_geometry_nonfinite_and_oversized_rejected(self):
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            root=Path(temp);points=root/'points';camera=root/'camera';points.write_bytes(b'original');camera.write_bytes(b'calibration')
            file=root/'dense';write(file,[[0,0,1]],[[1,2,3]],points,camera)
            points.write_bytes(b'another world')
            with self.assertRaises(ValueError):validate(file,points,camera)
            with self.assertRaises(ValueError):write(file,[[float('nan'),0,1]],[[1,2,3]],points,camera)
            points.write_bytes(b'original');raw=bytearray(file.read_bytes());struct.pack_into('<I',raw,8,2000001);file.write_bytes(raw)
            with self.assertRaises(ValueError):validate(file,points,camera)


if __name__=='__main__':unittest.main()
