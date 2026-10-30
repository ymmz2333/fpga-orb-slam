"""Gate regression: flattened names may pass; missing/ambiguous/II>1 may not."""
import unittest

from compare_front2 import resolve_loop


class LoopNameGateTests(unittest.TestCase):
    def test_exact_and_flattened_labels(self):
        for label in ('UnpackPairs', 'VITIS_LOOP_25_1_UnpackPairs'):
            found, proof = resolve_loop({label: {'II': 1, 'depth': 4}}, 'UnpackPairs')
            self.assertEqual(found, label)
            self.assertEqual(proof['II'], 1)

    def test_missing_and_ambiguous_fail(self):
        for loops in ({'Other_UnpackPairs': {'II': 1}},
                      {'UnpackPairs': {'II': 1}, 'VITIS_LOOP_25_1_UnpackPairs': {'II': 1}}):
            with self.assertRaises(ValueError):
                resolve_loop(loops, 'UnpackPairs')

    def test_ii_violation_is_preserved(self):
        _, proof = resolve_loop({'VITIS_LOOP_25_1_UnpackPairs': {'II': 2}}, 'UnpackPairs')
        self.assertNotEqual(proof['II'], 1)


if __name__ == '__main__':
    unittest.main()
