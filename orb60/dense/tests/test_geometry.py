import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dense.geometry import (backproject, project, letterbox_geometry, fit_inverse_depth,
                            VoxelMap, consistent_points, valid_pose)
from dense.ply import read_ply, write_ply


class GeometryTests(unittest.TestCase):
    def test_projection_with_translated_rotated_camera(self):
        k=np.array([[400.,0,320],[0,410,240],[0,0,1]])
        pose=np.array([[0.,0,1,2],[0,1,0,3],[-1,0,0,4],[0,0,0,1]])
        xyz=backproject(np.array([[320.,240],[420,240]]),np.array([2.,4.]),k,pose)
        np.testing.assert_allclose(xyz,[[4,3,4],[6,3,3]],atol=1e-8)
        uv,z=project(xyz,k,pose)
        np.testing.assert_allclose(uv,[[320,240],[420,240]],atol=1e-8)
        np.testing.assert_allclose(z,[2,4])

    def test_letterbox_intrinsics_preserve_pixel_centers(self):
        k=np.array([[640.,0,639.5],[0,640,359.5],[0,0,1]])
        result,roi,_=letterbox_geometry(1280,720,k)
        self.assertEqual(roi,(0,90,960,540))
        np.testing.assert_allclose(result,[[480,0,479.5],[0,480,359.5],[0,0,1]])

    def test_robust_inverse_depth_rejects_outliers(self):
        x=np.linspace(10,1000,100)
        z=1/(x*.002+.1)
        z[::3]*=4
        a,b,report=fit_inverse_depth(x,z,seed=4)
        self.assertAlmostEqual(a,.002,places=8)
        self.assertAlmostEqual(b,.1,places=8)
        self.assertGreaterEqual(report['inliers'],60)

    def test_invalid_and_degenerate_data(self):
        for x,z in [(np.ones(30),np.ones(30)),(np.arange(10),np.ones(10)),
                    (np.arange(30),np.full(30,np.nan))]:
            with self.assertRaises(ValueError):fit_inverse_depth(x,z)
        pose=np.eye(4);pose[0,0]=-1
        self.assertFalse(valid_pose(pose))
        with self.assertRaises(ValueError):backproject([[1,2]],[-1],np.eye(3),np.eye(4))

    def test_multiview_depth_rejects_wrong_pose_and_wrong_depth(self):
        k=np.array([[20.,0,10],[0,20,10],[0,0,1]])
        world=np.array([[0.,0,2],[.1,.1,2]])
        mask=np.ones((24,24),bool)
        good=(np.full((24,24),2.),mask,k,np.eye(4))
        np.testing.assert_equal(consistent_points(world,[good]),[True,True])
        bad=(np.full((24,24),8.),mask,k,np.eye(4))
        self.assertFalse(consistent_points(world,[bad]).any())
        pose=np.eye(4);pose[0,3]=100
        self.assertFalse(consistent_points(world,[(good[0],mask,k,pose)]).any())

    def test_voxel_capacity_rebins_and_preserves_weighted_color(self):
        points=np.array([[.1,0,1],[.2,0,1],[3.1,0,1],[7.1,0,1]])
        rgb=np.array([[255,0,0],[0,0,255],[0,255,0],[255,255,255]])
        voxel=VoxelMap(1,capacity=2);voxel.add(points,rgb)
        xyz,colors=voxel.arrays()
        self.assertLessEqual(len(xyz),2)
        self.assertEqual(int(voxel.counts.sum()),4)
        self.assertGreater(voxel.edge,1)
        self.assertTrue((colors>=0).all() and (colors<=255).all())

    def test_rgb_ply_roundtrip_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cloud.ply'
            xyz=np.array([[1,2,3],[-1,-2,4]],np.float32)
            rgb=np.array([[255,0,0],[0,0,255]],np.uint8)
            write_ply(path,xyz,rgb)
            actual,color=read_ply(path)
            np.testing.assert_array_equal(actual,xyz)
            np.testing.assert_array_equal(color,rgb)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):read_ply(path)


if __name__=='__main__':unittest.main()
