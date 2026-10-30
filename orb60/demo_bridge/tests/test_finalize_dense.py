import csv,json,tempfile,unittest
from pathlib import Path
import numpy as np
from orb60.demo_bridge.finalize_dense import build
from orb60.demo_bridge.dense_environment import POINT,validate

def table(path,values):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)

class FinalDense(unittest.TestCase):
    def fixture(self,root,observations=80):
        for d in ['tracking/map','tracking/map_for_zynq','dense/chunks','dense/anchors']:(root/d).mkdir(parents=True)
        folder=root/'tracking/map_for_zynq';camera=folder/'camera_orb.csv';camera.write_bytes(b'calibration')
        (root/'tracking/map/map_id.txt').write_text('1\n')
        angle=.25;r=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1.]])
        t=np.array([1.,-.4,.7]);pose=np.eye(4);pose[:3,:3]=r;pose[:3,3]=t
        row=dict(slam_timestamp_ns=123456789,map_id=1);row.update({'twc_%d%d'%(i,j):pose[i,j] for i in range(4) for j in range(4)})
        table(root/'tracking/map/final_frames.csv',[row]);table(root/'tracking/frames.csv',[dict(source_frame_id=42,slam_timestamp_ns=123456789)])
        rng=np.random.RandomState(42);local=rng.uniform([-.5,-.4,1],[.5,.4,4],size=(2200,3));world=2*local@r.T+t
        table(folder/'points.csv',[dict(point_id=i,x=p[0],y=p[1],z=p[2]) for i,p in enumerate(world[:80])])
        meta=dict(map_id=0,source_frame_index=42,points=len(local))
        (root/'dense/chunks/g.json').write_text(json.dumps(meta))
        points=np.empty(len(local),POINT);points['xyz']=local;points['rgb']=[10,70,220];points.tofile(root/'dense/chunks/g.bin')
        obs=[[100.,200.,*p.tolist(),i] for i,p in enumerate(local[:observations])]
        (root/'dense/anchors/g.json').write_text(json.dumps(dict(twc=np.eye(4).tolist(),observations=obs)))
        return folder,camera,world

    def test_final_pose_scale_reanchor_merged_map_and_rgb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,camera,world=self.fixture(root)
            report=build(root,folder,camera);self.assertGreater(report['points'],1000)
            self.assertAlmostEqual(report['accepted'][0]['inverse_depth_update']['slope'],.5,places=5)
            self.assertEqual(report['map_id'],1)
            raw=(folder/'dense_environment.bin').read_bytes();out=np.frombuffer(raw,POINT,offset=144)
            self.assertTrue(np.all(out['rgb']==[10,70,220]));validate(folder/'dense_environment.bin',folder/'points.csv',camera)
            np.testing.assert_allclose(out['xyz'].mean(axis=0),world.mean(axis=0),atol=.004)

    def test_insufficient_common_landmarks_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder,camera,_=self.fixture(root,observations=10)
            with self.assertRaisesRegex(ValueError,'No dense groups'):build(root,folder,camera)
            self.assertFalse((folder/'dense_environment.bin').exists())

if __name__=='__main__':unittest.main()
