#!/usr/bin/env python3
"""Independent small timing examples verify scientific aggregation semantics."""
import csv
import pathlib
import tempfile
import unittest

from analyze_a2 import analyze, category, percentile


class A2AnalysisTests(unittest.TestCase):
    def make_fixture(self, folder):
        states = [(-1, 1), (1, 2), (2, 2), (2, 2), (2, 3)]
        with (folder / "TrackingStates.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["frame_index", "sequence_index", "sequence_frame", "timestamp_s", "state_before", "state_after"])
            for index, (before, after) in enumerate(states):
                writer.writerow([index, 0, index, 1400000000+index*0.05, before, after])
        with (folder / "TrackingTimeStats.txt").open("w") as stream:
            stream.write("#Image Rect[ms], Image Resize[ms], ORB ext[ms], Stereo match[ms], IMU preint[ms], Pose pred[ms], LM track[ms], KF dec[ms], Total[ms]\n")
            for orb, total, pose in ((60,100,0), (70,200,0), (10,20,0), (10,100,3), (8,30,0)):
                stream.write("0,1,%s,0,0,%s,0,0,%s\n" % (orb, pose, total))
        (folder / "SessionInfo.txt").write_text("Number of Maps: 1\n")
        (folder / "program.log").write_text("Active map Reseting\nReseting Local Mapper...\nSystem Reseting\n")

    def test_state_partition_and_two_ratio_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary)
            self.make_fixture(folder)
            facts = analyze(folder, 5)
            self.assertEqual((facts["frames"], facts["initialization_frames"], facts["lost_frames"]), (2,2,1))
            self.assertAlmostEqual(facts["orb_ratio_frame_median"], 0.3)
            self.assertAlmostEqual(facts["orb_ratio_sums"], 1/6)
            self.assertEqual(facts["total_median_ms"], 60)
            self.assertEqual(facts["total_p95_ms"], 96)
            self.assertEqual(facts["total_gt50_fraction"], 0.5)
            self.assertEqual(facts["total_gt33_fraction"], 0.5)
            self.assertEqual(facts["active_map_resets"], 1)
            self.assertEqual(facts["full_resets"], 1)
            with (folder / "frames.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["orb_ratio"], "")
            self.assertEqual(rows[4]["orb_ratio"], "")

    def test_zero_padding_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary)
            self.make_fixture(folder)
            analyze(folder)
            with (folder / "module_summary.csv").open() as stream:
                row = next(row for row in csv.DictReader(stream) if row["category"] == "normal" and row["module"] == "pose_pred_ms")
            self.assertEqual(row["count"], "1")
            self.assertEqual(row["excluded_zero"], "1")
            self.assertEqual(float(row["mean"]), 3)

    def test_misaligned_output_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary)
            self.make_fixture(folder)
            lines = (folder / "TrackingStates.csv").read_text().splitlines()
            (folder / "TrackingStates.csv").write_text("\n".join(lines[:-1])+"\n")
            with self.assertRaisesRegex(RuntimeError, "row count"):
                analyze(folder)

    def test_incomplete_sequence_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = pathlib.Path(temporary)
            self.make_fixture(folder)
            with self.assertRaisesRegex(RuntimeError, "frame count"):
                analyze(folder, 6)

    def test_state_semantics(self):
        self.assertEqual(category(1,2), "initialization")
        self.assertEqual(category(2,0), "lost")
        self.assertEqual(category(3,2), "normal")
        self.assertEqual(category(0,3), "lost")
        with self.assertRaisesRegex(RuntimeError, "Unhandled"):
            category(2,5)

    def test_percentile_edge_case(self):
        self.assertEqual(percentile([9], 95), 9)
        self.assertEqual(percentile([20,100], 95), 96)


if __name__ == "__main__":
    unittest.main()
