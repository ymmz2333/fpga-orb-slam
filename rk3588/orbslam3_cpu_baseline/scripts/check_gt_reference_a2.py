#!/usr/bin/env python3
"""Independent official left-camera GT check for the ASL body->cam0 conversion."""
import argparse
import csv
import hashlib
import json
import pathlib

import numpy as np
from evaluate_a2 import associate

parser = argparse.ArgumentParser()
parser.add_argument("official", help="Official evaluation/Ground_truth/EuRoC_left_cam/MH01_GT.txt")
parser.add_argument("converted", help="Our groundtruth_cam0.tum")
parser.add_argument("--output", required=True)
args = parser.parse_args()
official = np.loadtxt(args.official, delimiter=",", comments="#")
official[:, 0] /= 1e9
derived = np.loadtxt(args.converted)
ri, ei = associate(derived[:, 0], official[:, 0])
error = np.linalg.norm(derived[ri, 1:4]-official[ei, 1:4], axis=1)
if len(error) != len(official) or max(error) > 1e-5:
    raise RuntimeError("Converted camera position differs from official left-camera GT")
result = dict(status="PASS", matched_poses=len(error), position_difference_max_m=float(max(error)),
              position_difference_median_m=float(np.median(error)),
              timestamp_difference_max_s=float(max(abs(derived[ri, 0]-official[ei, 0]))),
              official_sha256=hashlib.sha256(pathlib.Path(args.official).read_bytes()).hexdigest(),
              converted_sha256=hashlib.sha256(pathlib.Path(args.converted).read_bytes()).hexdigest(),
              scope="Positions only: APE translation metric")
output = pathlib.Path(args.output)
output.mkdir(parents=True, exist_ok=True)
(output / "gt_reference_check.json").write_text(json.dumps(result, indent=2))
with (output / "gt_reference_check.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(result))
    writer.writeheader()
    writer.writerow(result)
print("A2_GT_REFERENCE_PASS positions=%d max_difference_m=%.12g" % (len(error), max(error)))
