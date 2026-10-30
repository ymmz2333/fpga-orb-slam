"""Independent framing and timestamp examples used by the C0 audit."""
import unittest
from c0_inventory import nal_digest,interval_stats
class InventoryTests(unittest.TestCase):
    def test_slice_hash_ignores_transport_framing_and_parameter_sets(self):
        sps=b'\x67\x12\x34'; slice1=b'\x65\x01\x02'; slice2=b'\x41\x03\x04'
        annex=b'\0\0\0\1'+sps+b'\0\0\1'+slice1+b'\0\0\0\1'+slice2
        avcc=b''.join(len(x).to_bytes(4,'big')+x for x in (slice1,slice2))
        self.assertEqual(nal_digest(annex),nal_digest(avcc,avcc=True))
        self.assertNotEqual(nal_digest(annex),nal_digest(len(slice1).to_bytes(4,'big')+slice1,avcc=True))
        self.assertIsNone(nal_digest(b'\0\0\1'+sps))
    def test_bad_avcc_rejected(self):
        with self.assertRaises(ValueError): nal_digest(b'\0\0\0\x10\x65',avcc=True)
    def test_real_clock_gaps_are_not_flattened_to_nominal_fps(self):
        r=interval_stats([0,.033,.066,.266,.299])
        self.assertEqual(r['intervals'],4); self.assertEqual(r['gap_gt50ms'],1); self.assertEqual(r['stall_ge100ms'],1)
        self.assertAlmostEqual(r['median_ms'],33); self.assertAlmostEqual(r['max_ms'],200)
if __name__=='__main__': unittest.main()
