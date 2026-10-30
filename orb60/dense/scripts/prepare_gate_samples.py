"""Select actual SLAM keyframe timestamps and decode original video sequentially."""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True, type=Path)
    p.add_argument("--frames", required=True, type=Path)
    p.add_argument("--keyframes", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--width", type=int, default=518)
    p.add_argument("--height", type=int, default=392)
    a = p.parse_args()
    rows = {int(r["timestamp_ns"]): r for r in csv.DictReader(a.frames.open())}
    keys = sorted(set(int(Decimal(line.split()[0])) for line in
                      a.keyframes.read_text().splitlines() if line.strip()))
    if any(k not in rows for k in keys):
        raise ValueError("Keyframe timestamp not in source frame manifest")
    if len(keys) < a.count:
        raise ValueError("Not enough real SLAM keyframes")
    selected = [keys[i] for i in np.linspace(0, len(keys) - 1, a.count).round().astype(int)]
    wanted = {int(rows[k]["source_frame_index"]): (k, rows[k]) for k in selected}
    a.output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(a.video))
    if not cap.isOpened():
        raise ValueError("Cannot open original video")
    rotation = cap.get(cv2.CAP_PROP_ORIENTATION_META)
    output = []
    idx = 0
    while idx <= max(wanted):
        ok, bgr = cap.read()
        if not ok:
            raise ValueError("Original video ended before selected frame")
        if idx in wanted:
            timestamp, row = wanted[idx]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            # Fixed network tensor; resizing is explicit and identical for reference/NPU.
            resized = cv2.resize(rgb, (a.width, a.height), interpolation=cv2.INTER_CUBIC)
            tensor = (resized.astype(np.float32) / 255.0 -
                      np.array([0.485, 0.456, 0.406], np.float32)) / \
                     np.array([0.229, 0.224, 0.225], np.float32)
            tensor = np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])
            name = f"kf_{len(output):02d}"
            np.save(a.output / (name + ".input.npy"), tensor)
            tensor.tofile(a.output / (name + ".input.f32"))
            if not cv2.imwrite(str(a.output / (name + ".rgb.png")), bgr):
                raise IOError("Cannot save lossless original color frame")
            output.append(dict(id=name, source_frame_index=idx,
                               slam_frame_index=int(row["frame_index"]),
                               timestamp_ns=timestamp, mp4_pts_s=float(row["mp4_pts_s"]),
                               decoded_pts_ms=cap.get(cv2.CAP_PROP_POS_MSEC),
                               original_shape=list(rgb.shape), input_shape=list(tensor.shape),
                               input_sha256=hashlib.sha256(tensor.tobytes()).hexdigest()))
        idx += 1
    cap.release()
    with a.video.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    manifest = dict(video=str(a.video.resolve()), video_sha256=digest,
                    rotation_degrees=rotation, selection="20 evenly spaced final SLAM keyframe timestamps",
                    purpose="NPU compatibility gate only; not a dense reconstruction dataset",
                    input_layout="NCHW float32 RGB ImageNet normalized; no RKNN normalization",
                    frames=output)
    (a.output / "samples.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(samples=len(output), video_sha256=digest,
                          first_source=output[0]["source_frame_index"],
                          last_source=output[-1]["source_frame_index"])))


if __name__ == "__main__":
    main()
