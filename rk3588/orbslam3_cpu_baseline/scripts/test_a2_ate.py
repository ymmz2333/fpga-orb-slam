"""Independent analytic Sim3 and extrinsic fixtures, not MH01 measurements."""
import pathlib
import tempfile
import unittest

import numpy as np
from evaluate_a2 import associate, evaluate, umeyama


class ATETest(unittest.TestCase):
    def test_known_sim3(self):
        estimate = np.array([[0,0,0], [1,0,0], [0,2,0], [0,0,3], [1,2,4]], float)
        reference = np.column_stack((-2*estimate[:,1]+5, 2*estimate[:,0]-3, 2*estimate[:,2]+7))
        alignment, errors = umeyama(reference, estimate)
        self.assertAlmostEqual(alignment['scale'], 2)
        np.testing.assert_allclose(alignment['translation'], [5,-3,7], atol=1e-12)
        np.testing.assert_allclose(errors, 0, atol=1e-12)

    def test_degenerate_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Degenerate'):
            umeyama(np.zeros((4,3)), np.zeros((4,3)))

    def test_association_tolerance(self):
        ri, ei = associate([1,1.05,1.10,1.15], [1.004,1.052,1.20])
        self.assertEqual(ri.tolist(), [0,1])
        self.assertEqual(ei.tolist(), [0,1])

    def test_conversion_extrinsic_and_evo_crosscheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            folder = root / 'run'
            camera = root / 'dataset/mav0/cam0'
            gt = root / 'dataset/mav0/state_groundtruth_estimate0'
            for p in (folder, camera, gt):
                p.mkdir(parents=True)
            (camera / 'sensor.yaml').write_text('T_BS:\n  data: [1,0,0,1, 0,1,0,2, 0,0,1,3, 0,0,0,1]\n')
            points = [[0,0,0], [1,0,0], [0,2,0], [0,0,3], [1,2,4]]
            stamps = [1403636579763555584+i*50000000 for i in range(5)]
            q = 2**-0.5
            truth = '#timestamp,px,py,pz,qw,qx,qy,qz\n'
            raw = ''
            for stamp, (x,y,z) in zip(stamps, points):
                truth += '%d,%s,%s,%s,%s,0,0,%s\n' % (stamp,x,y,z,q,q)
                # Body rotation Z=90 deg maps camera lever arm [1,2,3] to [-2,1,3].
                raw += '%d %.12f %.12f %.12f 0 0 0 1\n' % (stamp,(x-2)/2,(y+1)/2,(z+3)/2)
            (gt / 'data.csv').write_text(truth)
            (folder / 'f_MH01.txt').write_text(raw)
            result = evaluate(folder, root / 'dataset')
            self.assertLess(result['ate_rmse_m'], 1e-10)
            np.testing.assert_allclose(np.loadtxt(folder / 'groundtruth_cam0.tum')[0,1:4], [-2,1,3])
            self.assertIn('cross-check passed', result['evaluation_method'])
            self.assertTrue((folder / 'camera.tum').read_text().startswith('1403636579.763555584'))
            # Upstream Tracking repeats its last pose/time during empty-pose lost frames.
            lines = raw.splitlines(True)
            (folder / 'f_MH01.txt').write_text(''.join(lines[:2]+[lines[1]]+lines[2:]))
            (folder / 'ape.zip').unlink()
            result = evaluate(folder, root / 'dataset')
            self.assertEqual(result['duplicate_export_rows'], 1)
            self.assertEqual(result['exported_poses'], 6)
            self.assertIn('cross-check passed', result['evaluation_method'])
            (folder / 'f_MH01.txt').write_text(''.join(lines[:2]+[lines[1].replace('0.500000000000','8.500000000000')]+lines[2:]))
            with self.assertRaisesRegex(RuntimeError, 'different poses'):
                evaluate(folder, root / 'dataset')


if __name__ == '__main__':
    unittest.main()
