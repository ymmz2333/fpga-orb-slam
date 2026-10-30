"""Regression checks for epoch-nanosecond rounding in native SLAM exports."""
import unittest
from golden_report_audited import filter_ok_trajectory


class ExportAssociation(unittest.TestCase):
    def setUp(self):
        self.stamps = [1403636579813555584 + 50000000*i for i in range(3)]
        self.features = [{'timestamp_ns': str(n)} for n in self.stamps]
        self.frames = [{'state_after': s} for s in ['2', '3', '2']]

    def test_round_trip_keeps_ok_frames_and_restores_exact_source_ns(self):
        raw = '\n'.join(f'{n+d}.000000 1 2 3 0 0 0 1'
                        for n,d in zip(self.stamps, [-128,0,128]))
        text, facts = filter_ok_trajectory(raw, self.features, self.frames)
        self.assertEqual([int(x.split()[0]) for x in text.splitlines()],
                         [self.stamps[0],self.stamps[2]])
        self.assertEqual(facts['max_export_rounding_ns'],128)
        self.assertEqual(facts['excluded_non_ok_rows'],1)

    def test_distant_or_conflicting_duplicate_export_is_rejected(self):
        with self.assertRaises(ValueError):
            filter_ok_trajectory(f'{self.stamps[0]+1001} 1 2 3 0 0 0 1',self.features,self.frames)
        line=f'{self.stamps[0]} 1 2 3 0 0 0 1'
        with self.assertRaises(ValueError):
            filter_ok_trajectory(line+'\n'+line.replace(' 1 2 3 ',' 4 2 3 '),self.features,self.frames)

    def test_identical_upstream_duplicates_preserve_evo_weighting(self):
        line=f'{self.stamps[0]} 1 2 3 0 0 0 1'
        text,facts=filter_ok_trajectory(line+'\n'+line,self.features,self.frames)
        self.assertEqual(len(text.splitlines()),2)
        self.assertEqual(facts['kept_ok_unique_frames'],1)
        self.assertEqual(facts['identical_duplicate_export_rows'],1)


if __name__=='__main__':unittest.main()
