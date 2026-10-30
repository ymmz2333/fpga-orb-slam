#!/usr/bin/env python3
"""Validate timing-file structure without reporting synthetic timing as a baseline."""
import csv
import math
import pathlib
import sys

output = pathlib.Path(sys.argv[1]).resolve()
root = pathlib.Path(__file__).resolve().parent.parent
frames = len((root / "runtime/smoke_input/timestamps.txt").read_text().splitlines())
expected_files = ["TrackingTimeStats.txt", "LocalMapTimeStats.txt", "LBA_Stats.txt", "SessionInfo.txt", "ExecMean.txt"]
for name in expected_files:
    if not (output / name).is_file():
        raise RuntimeError("Missing timing output: " + name)
with (output / "TrackingTimeStats.txt").open() as stream:
    header = next(stream).lstrip("#").strip().split(",")
    header = [field.strip() for field in header]
    rows = list(csv.reader(stream))
if header[2] != "ORB ext[ms]" or header[8] != "Total[ms]":
    raise RuntimeError("Unexpected timing columns: " + repr(header))
if len(rows) != frames:
    raise RuntimeError("Timing row count differs from input frame count")
for index, row in enumerate(rows):
    if len(row) != 9:
        raise RuntimeError("Wrong field count on frame %d" % index)
    values = [float(field) for field in row]
    if not all(math.isfinite(value) and value >= 0 for value in values):
        raise RuntimeError("Invalid timing value on frame %d" % index)
    if not (values[8] >= values[2] > 0):
        raise RuntimeError("ORB extraction/total time check failed on frame %d" % index)
if "ORB Extraction:" not in (output / "ExecMean.txt").read_text():
    raise RuntimeError("ORB Extraction summary is absent")
with (output / "verification.csv").open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["check", "status", "detail"])
    writer.writerow(["synthetic_only", "PASS", "not an accuracy/performance baseline"])
    writer.writerow(["timing_files", "PASS", ";".join(expected_files)])
    writer.writerow(["timing_rows", "PASS", len(rows)])
    writer.writerow(["orb_field", "PASS", "column 3: ORB ext[ms]"])
    writer.writerow(["total_field", "PASS", "column 9: Total[ms]"])
print("A1_SYNTHETIC_TIMING_SMOKE_PASS", flush=True)
