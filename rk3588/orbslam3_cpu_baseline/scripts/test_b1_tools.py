"""Independent corruption and state/ideal-bound fixtures; no MH01 results invented."""
import csv
import pathlib
import struct
import tempfile
import unittest
from verify_feature_files import HEADER, RECORD, verify
from test_a2_analysis import A2AnalysisTests
from analyze_b1 import analyze_features

class FeatureTests(unittest.TestCase):
    def test_independent_packet_and_corruptions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); packet=root/'point.orb'; memory=root/'point.bin'
            ns=1403636579763555584
            point=RECORD.pack(12.25,23.5,2,45.,31.,42.,-1,0,bytes(range(32)))
            header=HEADER.pack(b'ORBFEAT\0',1,64,64,0,0,ns,752,480,1,8,1.2,1000,32,0,0,0)
            memory.write_bytes(point); packet.write_bytes(header+point)
            self.assertTrue(verify(packet,memory,ns,0)['byte_equal'])
            for offset in (0,8,14,16,24,36,40,44,48,52,60):
                corrupt=bytearray(header+point); corrupt[offset]^=1; packet.write_bytes(corrupt)
                with self.assertRaises(ValueError): verify(packet,memory,ns,0)
            packet.write_bytes(header+point); memory.write_bytes(point[:-1]+b'\xff')
            with self.assertRaisesRegex(ValueError,'memory byte mismatch'): verify(packet,memory,ns,0)
            memory.write_bytes(point); packet.write_bytes(header+point+b'\0')
            with self.assertRaisesRegex(ValueError,'length'): verify(packet,memory,ns,0)

    def test_remaining_is_per_frame_and_lost_not_in_normal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); folder=root/'run'; folder.mkdir()
            A2AnalysisTests().make_fixture(folder)
            truth=root/'dataset/mav0/state_groundtruth_estimate0'; truth.mkdir(parents=True)
            truth.joinpath('data.csv').write_text('#timestamp\n1400000000000000000\n1400000000170000000\n')
            with (folder/'FeatureTimeStats.csv').open('w',newline='') as f:
                w=csv.writer(f); w.writerow(['frame_index','timestamp_ns','role','count','extractor_calls','read_ms','decode_ms','native_ms','dump_ms','auxiliary_ms','inliers'])
                for i in range(5): w.writerow([i,1400000000000000000+i*50000000,0,1000,0,1,2,0,0,0,50 if i in (2,3) else -1])
            facts=analyze_features(folder,root/'dataset','inject',5)
            self.assertEqual(facts['normal_frames'],2)
            self.assertEqual(facts['remaining_ms_median'],50) # median of (20-10,100-10), not file-read subtraction
            self.assertEqual(facts['read_ms_median'],1)
            self.assertEqual(facts['decode_ms_median'],2)
            self.assertEqual(facts['tail_lost_frames'],1)
            self.assertEqual(facts['inliers_valid_frames'],2)
            self.assertEqual(facts['orb_ratio_sums'],'')
            with self.assertRaisesRegex(RuntimeError,'extractor call'):
                analyze_features(folder,root/'dataset','native',5)

if __name__=='__main__': unittest.main()
