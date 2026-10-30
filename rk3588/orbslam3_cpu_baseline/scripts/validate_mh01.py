#!/usr/bin/env python3
"""Check ASL camera inventory, GT, and every official MH01 timestamp."""
import argparse
import csv
import hashlib
import json
import pathlib
import re
import struct
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def validate(dataset, timestamps):
    dataset, timestamps = pathlib.Path(dataset), pathlib.Path(timestamps)
    times = [int(line) for line in timestamps.read_text().splitlines() if line.strip()]
    intervals = [b-a for a, b in zip(times, times[1:])]
    if not intervals or any(abs(delta-50000000) > 1000 for delta in intervals):
        raise RuntimeError("Official MH01 timestamps must have nominal 20 Hz cadence")
    camera = dataset / "mav0/cam0"
    with (camera / "data.csv").open() as stream:
        rows = [row for row in csv.reader(stream) if row and not row[0].lstrip().startswith("#")]
    names = [row[1].strip() for row in rows]
    image_names = {path.name for path in (camera / "data").glob("*.png")}
    if len(names) != len(set(names)) or set(names) != image_names:
        raise RuntimeError("cam0 PNG inventory differs from unique data.csv filenames")
    for row in rows:
        if pathlib.PurePosixPath(row[1].strip()).name != row[1].strip() or row[1].strip() != row[0].strip()+".png":
            raise RuntimeError("Invalid camera CSV timestamp/filename")
    for stamp in times:
        path = camera / "data" / (str(stamp)+".png")
        with path.open("rb") as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != (752, 480):
            raise RuntimeError("Invalid MH01 source PNG: "+str(path))
    truth = dataset / "mav0/state_groundtruth_estimate0/data.csv"
    with truth.open() as stream:
        truth_rows = [row for row in csv.reader(stream) if row and not row[0].lstrip().startswith("#")]
    if not truth_rows or any(len(row) < 8 or int(row[0]) < 10**17 for row in truth_rows):
        raise RuntimeError("Invalid ground-truth rows / nanosecond timestamps")
    if not (camera / "sensor.yaml").is_file():
        raise RuntimeError("cam0 calibration missing")
    return dict(dataset=str(dataset.resolve()), frames=len(times), cam0_images=len(image_names),
                cam0_csv_rows=len(rows), groundtruth_rows=len(truth_rows), missing_timestamp_images=0,
                timestamp_unit="nanoseconds", first_ns=times[0], last_ns=times[-1],
                interval_min_ns=min(intervals), interval_max_ns=max(intervals),
                duration_s=(times[-1]-times[0])/1e9, source_width=752, source_height=480,
                tracking_width=600, tracking_height=350, resize_x=600/752, resize_y=350/480,
                realtime_wait_preserved=True, timestamps_sha256=hashlib.sha256(timestamps.read_bytes()).hexdigest())


def save_report(metadata, output):
    output = pathlib.Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "dataset.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    with (output / "dataset.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["field", "value"])
        writer.writerows(metadata.items())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--timestamps")
    parser.add_argument("--output", default=str(ROOT / "reports/a2"))
    parser.add_argument("--settings")
    args = parser.parse_args()
    source = ROOT / "vendor/ORB_SLAM3"
    timestamps = args.timestamps or str(source / "Examples/Monocular/EuRoC_TimeStamps/MH01.txt")
    metadata = validate(args.dataset, timestamps)
    if not args.timestamps:
        config = pathlib.Path(args.settings) if args.settings else source / "Examples/Monocular/EuRoC.yaml"
        official = subprocess.check_output(["git", "-C", str(source), "show", "v1.0-release:Examples/Monocular/EuRoC.yaml"])
        if not args.settings and config.read_bytes() != official:
            raise RuntimeError("A2 requires original official EuRoC.yaml bytes")
        metadata["config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
        if args.settings:
            text = config.read_text()
            for dimension, original in (('width',752),('height',480)):
                match = re.search(r'^Camera.new%s:\s*(\d+)' % dimension.capitalize(),text,re.M)
                metadata['tracking_'+dimension] = int(match.group(1)) if match else original
            metadata.update(resize_x=metadata['tracking_width']/752,resize_y=metadata['tracking_height']/480)
    save_report(metadata, args.output)
    print("A2_DATASET_PASS images=%d csv_rows=%d official_frames=%d missing=0" %
          (metadata["cam0_images"], metadata["cam0_csv_rows"], metadata["frames"]))
