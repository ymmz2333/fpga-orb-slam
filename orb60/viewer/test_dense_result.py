"""Synthetic artifact fixtures test display bounds; never used as demo geometry."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from dense_result import DenseResult
from dense.ply import write_ply


class DenseLoaderTests(unittest.TestCase):
    def make_map(self,root,mid,count):
        folder=root/('map_%d'%mid);folder.mkdir()
        xyz=np.zeros((count,3),np.float32);xyz[:,0]=np.arange(count)*.001+mid*100
        rgb=np.tile(np.array([[10,120,250]],np.uint8),(count,1))
        write_ply(folder/'dense.ply',xyz,rgb);write_ply(folder/'sparse.ply',xyz[:1],rgb[:1])
        (folder/'poses.json').write_text(json.dumps([dict(twc=np.eye(4).tolist())]))
        report=dict(map_id=mid,points=count,cloud='dense.ply',sparse='sparse.ply',poses='poses.json')
        (folder/'result.json').write_text(json.dumps(report))
        return report

    def test_display_cap_and_map_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            maps=[self.make_map(root,0,200123),self.make_map(root,1,3)]
            (root/'result.json').write_text(json.dumps(dict(maps=maps)))
            a=DenseResult(root,0);b=DenseResult(root,1)
            self.assertEqual(len(a.xyz),200123)
            self.assertEqual(len(a.sampled()[0]),200000)
            np.testing.assert_array_equal(a.indices,DenseResult(root,0).indices)
            self.assertTrue((b.xyz[:,0]>=100).all())
            np.testing.assert_array_equal(a.sampled()[1][0],[10,120,250])

    def test_escaped_artifact_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_map(root,0,2)
            path=root/'map_0/result.json';report=json.loads(path.read_text())
            report['cloud']='../outside.ply';path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):DenseResult(path)


if __name__=='__main__':unittest.main()
