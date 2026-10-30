"""B2 regression gates: inject timing semantics, format rejection and single-change matrix."""
import csv,json,pathlib,tempfile,unittest
import cv2
from analyze_b2 import analyze
from analyze_c import analyze_run
from batch_b3 import schedule
from test_a2_analysis import A2AnalysisTests
from verify_b2_corpus import verify
from verify_feature_files import HEADER,RECORD
ROOT=pathlib.Path(__file__).resolve().parent.parent

def fixture(root):
    A2AnalysisTests().make_fixture(root)
    with (root/'TrackingStates.csv').open(newline='') as f:states=list(csv.DictReader(f))
    for i,row in enumerate(states):row['timestamp_s']=float(1400000000000000000+i*50000000)*1e-9
    with (root/'TrackingStates.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(states[0]));w.writeheader();w.writerows(states)
    with (root/'FeatureTimeStats.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['frame_index','timestamp_ns','extractor_calls','inliers','read_ms','decode_ms','native_ms','count'])
        for i in range(5):w.writerow([i,1400000000000000000+i*50000000,0,50,0.1,0.2,0,100])
    with (root/'MapStateStats.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['frame_index','map_id','relocalized'])
        for i in range(5):w.writerow([i,7,0])
    (root/'Diagnostics_maps.csv').write_text('map_id,keyframes,map_points,trajectory_file\n7,4,300,x.txt\n')

class B2Tests(unittest.TestCase):
    def test_inject_slot_is_not_native_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);fixture(root)
            d=dict(name='synthetic',kind='prepared',path=tmp,width=960,height=720,intrinsics_label='借用内参，未本机标定')
            result=analyze(root,d,'V0',5)
            self.assertEqual(result['state_ok_fraction'],.6)
            self.assertEqual(result['orb_slot_semantics'],'file_read_decode')
            self.assertEqual(result['orb_ratio_frame_median'],'')
            self.assertEqual(result['read_ms_median'],.1)
            self.assertGreater(result['remaining_ms_median'],0)
            with self.assertRaises(ValueError):analyze_run(root,5) # Native default still rejects zero extractor calls.
    def test_header_and_quantized_angle_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);ns=1400000000000000000
            stamps=root/'timestamps.txt';stamps.write_text(str(ns)+'\n')
            config=root/'A8.yaml';config.write_text('ORBextractor.nLevels: 8\nORBextractor.scaleFactor: 1.2\nORBextractor.nFeatures: 1000\nDesign.angle_bins: 8\nDesign.grid: 0\n')
            for role,name in enumerate(('normal','initialization')):
                (root/name).mkdir();header=HEADER.pack(b'ORBFEAT\0',1,64,64,role,0,ns,752,480,1,8,1.2,1000*(5 if role else 1),32,0,1,0)
                record=RECORD.pack(100.,100.,0,45.,31.,50.,-1,0,bytes(32))
                (root/name/(str(ns)+'.orb')).write_bytes(header+record)
            self.assertEqual(verify(root,stamps,config,752,480)['files'],2)
            path=root/'normal'/(str(ns)+'.orb');data=path.read_bytes()
            path.write_bytes(data[:64]+RECORD.pack(100.,100.,0,46.,31.,50.,-1,0,bytes(32)))
            with self.assertRaises(ValueError):verify(root,stamps,config,752,480)
            path.write_bytes(b'BADMAGIC'+data[8:])
            with self.assertRaises(ValueError):verify(root,stamps,config,752,480)
    def test_single_change_matrix_and_150_run_schedule(self):
        plan=json.loads((ROOT/'configs/b2/design_candidates.json').read_text(encoding='utf-8'))
        self.assertEqual(list(plan['variants']),['native','V0','P1','P2','F','G','A8','A32','B','MIN'])
        self.assertEqual(plan['variants']['F'],{'fixed_fast':1})
        self.assertEqual(plan['variants']['G'],{'grid':1})
        self.assertEqual(plan['variants']['B'],{'skip_blur':1})
        self.assertEqual(plan['variants']['A8'],{'angle_bins':8})
        self.assertEqual(plan['variants']['A32'],{'angle_bins':32})
        items=schedule(dict(plan=plan,datasets=[dict(name=n) for n in ('MH01','tello1','tello2')]))
        self.assertEqual(len(items),150)
        for run in range(1,6):
            group=[r for r in items if r['run_index']==run]
            self.assertEqual([r['variant'] for r in group[:3]],['native']*3)
            self.assertEqual(len({r['folder'] for r in group}),30)
if __name__=='__main__':unittest.main()
