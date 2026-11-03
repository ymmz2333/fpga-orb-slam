import csv
from pathlib import Path
import tempfile
import unittest
from orb60.kv260.source_frame_map import SourceFrameMap


class SourceFrameMapTest(unittest.TestCase):
    def test_exact_integer_timestamps_survive_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.csv';journal=SourceFrameMap(path)
            for i in range(8200):journal.append(1793620000000000000+i*33333333,i)
            journal.close()
            with path.open(newline='') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),4104)
            self.assertEqual(int(rows[-1]['timestamp_ns']),1793620000000000000+8199*33333333)
            self.assertEqual(int(rows[-1]['source_frame_index']),8199)
            self.assertEqual(int(rows[0]['source_frame_index']),4096)

    def test_duplicate_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=SourceFrameMap(Path(folder)/'source.csv')
            try:
                journal.append(1234567890123456789,0)
                with self.assertRaises(ValueError):journal.append(1234567890123456789,1)
                with self.assertRaises(ValueError):journal.append(1234567890123456790,0)
            finally:journal.close()


if __name__=='__main__':unittest.main()
