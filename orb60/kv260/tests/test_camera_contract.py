from pathlib import Path
import tempfile
import unittest
from orb60.kv260.camera_contract import from_yaml, validate_pair
from orb60.demo_bridge.calibration import read


class CameraContract(unittest.TestCase):
    def test_modern_camera1_and_optional_k3(self):
        text = '%YAML:1.0\nFile.version: "1.0"\nCamera.type: "PinHole"\nCamera.width: 960\nCamera.height: 720\n'
        text += '\n'.join('Camera1.'+k+': '+str(v) for k,v in dict(fx=910.072,fy=914.094,cx=485.523,cy=336.718,k1=-.005941,k2=.055161,p1=-.006094,p2=.003192).items())+'\n'
        with tempfile.TemporaryDirectory() as folder:
            yaml=Path(folder)/'camera.yaml';yaml.write_text(text)
            csv=Path(folder)/'camera.csv';csv.write_bytes(from_yaml(yaml))
            self.assertEqual(read(csv.read_bytes())['fx'],910.072)
            self.assertEqual(read(csv.read_bytes())['d4'],0)
            self.assertIn(b'960,720,',csv.read_bytes())
            validate_pair(csv,yaml)
            csv.write_bytes(csv.read_bytes().replace(b'910.072',b'900.072'))
            with self.assertRaisesRegex(ValueError,'differ'):validate_pair(csv,yaml)
            yaml.write_text(text.replace('Camera1.fx: 910.072','Camera1.fx: 0'))
            with self.assertRaisesRegex(ValueError,'Invalid calibration'):from_yaml(yaml)
            yaml.write_text(text.replace('Camera1.fx: 910.072\n',''))
            with self.assertRaisesRegex(ValueError,'Missing SLAM calibration'):from_yaml(yaml)


if __name__=='__main__':unittest.main()
