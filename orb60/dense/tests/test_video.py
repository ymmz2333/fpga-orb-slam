import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dense.video import working_image,camera_config


class VideoTests(unittest.TestCase):
    def test_portrait_letterbox_excludes_artificial_border(self):
        bgr=np.full((800,400,3),(1,2,250),np.uint8)
        cam=camera_config(None,400,800,True)
        work,mask,k,roi,_=working_image(bgr,cam)
        self.assertEqual(roi,(300,0,360,720))
        self.assertFalse(mask[:,0:300].any())
        np.testing.assert_array_equal(work[300,400],[1,2,250])
        self.assertAlmostEqual(k[0,2],479.5)
        self.assertAlmostEqual(k[1,2],359.5)

    def test_rotation_swaps_intrinsics_and_color_corners(self):
        bgr=np.zeros((400,800,3),np.uint8)
        bgr[:200,:400]=[0,0,255]
        cam=dict(k=[[700,0,399.5],[0,600,199.5],[0,0,1]],distortion=[0]*5,width=800,height=400)
        work,mask,k,roi,_=working_image(bgr,cam,90)
        self.assertEqual(roi,(300,0,360,720))
        np.testing.assert_array_equal(work[100,600],[0,0,255])
        np.testing.assert_array_equal(work[600,600],[0,0,0])
        self.assertAlmostEqual(k[0,0],540)
        self.assertAlmostEqual(k[1,1],630)

    def test_unknown_camera_requires_explicit_mode(self):
        with self.assertRaises(ValueError):camera_config(None,1920,1080)
        cam=camera_config(None,1920,1080,True)
        self.assertEqual(cam['mode'],'explicit_approximate')
        self.assertEqual(cam['k'][0][0],1920)


if __name__=='__main__':unittest.main()
