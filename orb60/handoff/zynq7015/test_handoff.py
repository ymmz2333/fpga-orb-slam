"""Negative acceptance cases: a coordinate/byte error must not become a PASS."""
import tempfile
from pathlib import Path
import unittest
import numpy as np
from common import RECORD,Features,save,write_rows,pose_fields
from compare import compare
from build_map import raw_pose

class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.base=Path.cwd().resolve();self.temp=tempfile.TemporaryDirectory(prefix='orb60-acceptance-',dir=self.base)
        self.root=Path(self.temp.name).resolve();self.map=self.root/'map';self.map.mkdir()
        save(self.map/'map.json',dict(reference_median_depth=10))
        self.ref=[]
        for i in range(4):
            p=np.eye(4);p[0,3]=i
            self.ref.append(dict(frame_index=i,source_frame_index=i+24,timestamp_ns=1000+i,map_id=0,pose_valid=1,**pose_fields(p)))
        self.reference=self.root/'reference.csv';write_rows(self.reference,self.ref)
    def tearDown(self):
        if not self.root.is_relative_to(self.base) or self.root==self.base:raise ValueError('Unsafe test cleanup path')
        self.temp.cleanup()
    def check(self,data):
        path=self.root/'candidate.csv';write_rows(path,data)
        return compare(self.reference,path,self.map,self.root/'comparison')
    def test_identical_regression(self):self.assertEqual(self.check(self.ref)['status'],'PASS')
    def test_scale_error_is_not_aligned_away(self):
        data=[dict(r,twc_03=float(r['twc_03'])*2) for r in self.ref];self.assertEqual(self.check(data)['status'],'FAIL')
    def test_missing_coverage_fails(self):self.assertEqual(self.check(self.ref[:2])['status'],'FAIL')
    def test_duplicate_frame_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.check(self.ref+[self.ref[0]])
    def test_timestamp_error_rejected(self):
        with self.assertRaisesRegex(ValueError,'Timestamp'):self.check([dict(self.ref[0],timestamp_ns=1)]+self.ref[1:])
    def test_wrong_world_reflection_rejected(self):
        with self.assertRaisesRegex(ValueError,'rigid'):self.check([dict(self.ref[0],twc_00=-1)]+self.ref[1:])
    def test_empty_and_nonempty_feature_frames(self):
        folder=self.root/'features';folder.mkdir();write_rows(folder/'frames.csv',[
            dict(frame_index=0,count=0,record_offset=0),dict(frame_index=1,count=1,record_offset=0)])
        np.zeros(1,RECORD).tofile(folder/'features.bin');data=Features(folder)
        self.assertEqual(len(data.frame(0)),0);self.assertEqual(len(data.frame(1)),1)
        data.close()
        (folder/'features.bin').write_bytes(bytes(63))
        with self.assertRaisesRegex(ValueError,'Truncated'):Features(folder)
    def test_zero_quaternion_rejected(self):
        with self.assertRaisesRegex(ValueError,'quaternion'):raw_pose('1 0 0 0 0 0 0 0'.split())

if __name__=='__main__':unittest.main()
