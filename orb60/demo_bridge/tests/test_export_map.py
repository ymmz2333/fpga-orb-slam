"""Map export selection preserves geometry and actual descriptor associations."""
import hashlib
from pathlib import Path
import tempfile
import subprocess
import unittest

from orb60.demo_bridge.export_map import prepare
from orb60.demo_bridge.map_bundle import rows, seal, validate
from .offline_gate import bundle, write_rows, ROOT, OUT


class ExportMap(unittest.TestCase):
    def test_multilevel_duplicates_support_and_descriptor_identity(self):
        with tempfile.TemporaryDirectory(dir=OUT) as directory:
            source=Path(directory)/'raw'
            camera=bundle(source)
            (source/'map_id.txt').write_text('7\n')
            obs=rows(source/'observations.csv')
            raw=bytearray((source/'observation_descriptors.bin').read_bytes())
            for i,o in enumerate(obs):
                o.update(error_px=1,feature_index=i,observations=4)
            # Duplicate has better reprojection error and different real bytes.
            extra=dict(obs[0]);extra.update(error_px=.5,descriptor_row=len(obs),feature_index=100)
            obs.append(extra);raw.extend(b'\xff'*32)
            # Point 12 only has two distinct keyframes after quality filtering.
            obs=[o for o in obs if not (int(o['point_id'])==12 and int(o['keyframe_id'])>=2)]
            old=bytes(raw)
            raw=bytearray()
            for i,o in enumerate(obs):
                at=int(o['descriptor_row']);raw.extend(old[at*32:(at+1)*32]);o['descriptor_row']=i
            write_rows(source/'observations.csv',obs)
            (source/'observation_descriptors.bin').write_bytes(raw)
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
            output=Path(directory)/'selected'
            report=prepare(source,output)
            self.assertEqual(report['duplicate_observations'],1)
            self.assertEqual(report['output_points'],11)
            self.assertEqual(report['output_observations'],44)
            self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()})
            selected=rows(output/'observations.csv')
            data=(output/'observation_descriptors.bin').read_bytes()
            winner=next(o for o in selected if int(o['point_id'])==1 and int(o['keyframe_id'])==0)
            self.assertEqual(int(winner['feature_index']),100)
            at=int(winner['descriptor_row']);self.assertEqual(data[at*32:(at+1)*32],b'\xff'*32)
            reps=(output/'representative_descriptors.bin').read_bytes()
            for i,p in enumerate(rows(output/'points.csv')):
                at=int(p['representative_observation_row'])
                self.assertEqual(reps[i*32:(i+1)*32],data[at*32:(at+1)*32])
                self.assertEqual(int(selected[at]['point_id']),int(p['point_id']))
            seal(output,camera,7)
            self.assertEqual(validate(output,camera.read_bytes())['points'],11)
            installer=OUT/'native/zynq-map-install.exe'
            version=validate(output,camera.read_bytes())['version']
            store=Path(directory)/'store'
            result=subprocess.run([installer,store,camera,output,version],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('MAP_INSTALL_VERIFIED '+version,result.stdout)
            pointer=(store/'current').read_bytes()
            (output/'observations.csv').write_bytes(b'corrupt')
            result=subprocess.run([installer,store,camera,output,version],capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((store/'current').read_bytes(),pointer)
            again=Path(directory)/'again';prepare(source,again)
            for name in ('points.csv','observation_descriptors.bin','representative_descriptors.bin'):
                self.assertEqual((output/name).read_bytes(),(again/name).read_bytes())

    def test_invalid_source_is_not_silently_repaired(self):
        with tempfile.TemporaryDirectory(dir=OUT) as directory:
            source=Path(directory)/'raw';bundle(source)
            obs=rows(source/'observations.csv')
            for i,o in enumerate(obs):o.update(error_px=1,feature_index=i)
            obs[0]['descriptor_row']=999
            write_rows(source/'observations.csv',obs)
            with self.assertRaisesRegex(ValueError,'Invalid source'):
                prepare(source,Path(directory)/'out')


if __name__=='__main__':unittest.main()
