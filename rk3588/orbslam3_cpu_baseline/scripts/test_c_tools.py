"""Independent irregular-clock, recovery-map and checkerboard projection checks."""
import csv,json,pathlib,tempfile,unittest
from decimal import Decimal
import cv2,numpy as np
from prepare_c import relative_ns
from analyze_c import analyze_run,check_timestamp
from calibrate_camera import calibrate
from test_a2_analysis import A2AnalysisTests
class CTests(unittest.TestCase):
    def test_c_yaml_uses_v1_integer_nominal_fps(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        files=sorted((root/'configs/c').glob('*provisional.yaml'))
        self.assertEqual(len(files),3)
        for path in files:
            f=cv2.FileStorage(str(path),cv2.FILE_STORAGE_READ)
            self.assertTrue(f.getNode('Camera.fps').isInt(),path.name)
            self.assertEqual(f.getNode('Camera.fps').real(),30)
            self.assertTrue(f.getNode('Camera1.fx').isReal(),path.name)
            f.release()
    def test_timestamp_matches_actual_reader_rounding(self):
        # Values copied from the board's failed smoke-check raw logs.
        check_timestamp('1400000000100000000','1400000000.1000001')
        check_timestamp('1000000001','1.000000001')
        with self.assertRaises(ValueError):
            check_timestamp('1400000000150000000','1400000000.1000001')
    def test_clock_keeps_subframe_gap(self):
        self.assertEqual(relative_ns(Decimal('12345.800000001'),Decimal('12345.6')),1200000001)
        self.assertEqual(relative_ns(Decimal('12345.6'),Decimal('12345.6')),1000000000)
    def test_loss_is_not_claimed_relocalized_when_no_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); A2AnalysisTests().make_fixture(root)
            # This fixture also has integer-nanosecond feature records, so its
            # state log must use mono_euroc's double multiplication conversion.
            path=root/'TrackingStates.csv'
            with path.open(newline='') as f: states=list(csv.DictReader(f))
            for i,row in enumerate(states):
                row['timestamp_s']=float(1400000000000000000+i*50000000)*1e-9
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(states[0])); w.writeheader(); w.writerows(states)
            with (root/'FeatureTimeStats.csv').open('w',newline='') as f:
                w=csv.writer(f); w.writerow(['frame_index','timestamp_ns','extractor_calls','inliers'])
                for i in range(5): w.writerow([i,1400000000000000000+i*50000000,1,50 if i in (2,3) else -1])
            with (root/'MapStateStats.csv').open('w',newline='') as f:
                w=csv.writer(f); w.writerow(['frame_index','map_id','relocalized'])
                for i in range(5): w.writerow([i,7,0])
            (root/'Diagnostics_maps.csv').write_text('map_id,keyframes,map_points,trajectory_file\n7,4,300,x.txt\n')
            facts=analyze_run(root,5)
            self.assertEqual(facts['first_initialization_frame'],2); self.assertEqual(facts['state_ok_fraction'],.6)
            self.assertEqual(facts['loss_segments'],1); self.assertEqual(facts['same_map_recoveries'],0)
            self.assertEqual(facts['relocalized_frames'],0); self.assertEqual(facts['inliers_median'],50)
    def test_calibration_recovers_known_projected_camera(self):
        obj=np.zeros((54,3),np.float32); obj[:,:2]=np.mgrid[0:9,0:6].T.reshape(-1,2)*.025
        K=np.array([[900.,0,480.],[0,910.,360.],[0,0,1.]])
        objects=[]; images=[]
        for i in range(15):
            r=np.array([.1+.03*i,-.3+.035*i,.02*i]); t=np.array([-.1+.015*i,-.06+.008*i,.5+.025*i])
            img,_=cv2.projectPoints(obj,r,t,K,np.zeros(5)); objects.append(obj.copy()); images.append(img)
        rms,actual,D,errors=calibrate(objects,images,(960,720),K.copy())
        self.assertLess(rms,.001); self.assertTrue(np.allclose(actual,K,atol=.03)); self.assertEqual(len(errors),15)
        with self.assertRaises(ValueError): calibrate(objects[:2],images[:2],(960,720),K.copy())
if __name__=='__main__': unittest.main()
