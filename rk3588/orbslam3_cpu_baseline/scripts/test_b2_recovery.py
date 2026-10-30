"""Protect existing failures/outputs and exclude feature corpora from result exports."""
import hashlib,json,pathlib,tarfile,tempfile,unittest
from package_b2 import package
from resume_b2 import existing_corpus_check,select_recoveries

class RecoveryTests(unittest.TestCase):
    def test_only_verified_input_failures_selected_without_mutating_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)
            items=[dict(dataset='tello',variant='B',folder='tello__B',status='FAILED'),
                dict(dataset='tello',variant='F',folder='tello__F',status='FAILED'),
                dict(dataset='tello',variant='MIN',folder='tello__MIN')]
            state=dict(schedule=items,current='tello__MIN');before=json.dumps(state,sort_keys=True)
            for name,error in [('B',b'libpng error: IDAT: CRC error'),('F',b'Segmentation fault')]:
                folder=root/'runs'/('tello__'+name);folder.mkdir(parents=True);(folder/'program.log').write_bytes(error)
            (root/'tello__MIN_generate.log').write_bytes(b'libpng error: IDAT: CRC error')
            selected=select_recoveries(state,root)
            self.assertEqual([i['variant'] for i in selected],['B','MIN'])
            self.assertEqual(selected[0]['recovery_of'],'tello__B')
            self.assertEqual(json.dumps(state,sort_keys=True),before)
    def test_existing_corpus_requires_exact_original_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);(root/'normal').mkdir();(root/'checks').mkdir()
            p=root/'normal/100.orb';p.write_bytes(b'original')
            (root/'checks/packet_verification.csv').write_text('timestamp_ns,role,sha256\n100,0,'+hashlib.sha256(p.read_bytes()).hexdigest()+'\n')
            self.assertEqual(existing_corpus_check(root,root/'checks'),1)
            p.write_bytes(b'mutated')
            with self.assertRaises(ValueError):existing_corpus_check(root,root/'checks')
    def test_package_preserves_failure_bytes_and_ignores_previous_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);(root/'corpus').mkdir();(root/'corpus/large.orb').write_bytes(b'features')
            (root/'failure.log').write_bytes('输入失败\r\n'.encode());(root/'batch_state.json').write_text('{}')
            (root/'results.tar.gz').write_bytes(b'stale');(root/'raw_manifest.csv').write_text('stale')
            digest=package(root);self.assertEqual(digest,hashlib.sha256((root/'results.tar.gz').read_bytes()).hexdigest())
            with tarfile.open(root/'results.tar.gz') as archive:
                names=archive.getnames();self.assertNotIn('corpus/large.orb',names);self.assertNotIn('results.tar.gz',names)
                self.assertNotIn('batch_state.json',names);self.assertEqual(archive.extractfile('failure.log').read(),(root/'failure.log').read_bytes())
if __name__=='__main__':unittest.main()
