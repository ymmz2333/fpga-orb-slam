#!/usr/bin/env python3
"""Derive state-stratified timing CSVs from aligned real per-frame measurements."""
import argparse
import csv
import json
import math
import pathlib
import re
import statistics

FIELDS = ["image_rect_ms", "image_resize_ms", "orb_ms", "stereo_ms", "imu_ms", "pose_pred_ms",
          "local_map_track_ms", "keyframe_decision_ms", "total_ms"]


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered)-1)*percent/100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def category(before, after):
    if after in (3, 4):
        return "lost"
    if before in (-1, 0, 1) and after in (0, 1, 2):
        return "initialization"
    if before in (2, 3, 4) and after == 2:
        return "normal"
    if after in (0, 1) and before in (2, 3, 4):
        return "lost"
    raise RuntimeError("Unhandled tracking state transition: %s -> %s" % (before, after))


def describe(values):
    if not values:
        return {"count": 0, "mean": "", "median": "", "p95": "", "min": "", "max": ""}
    return dict(count=len(values), mean=statistics.mean(values), median=statistics.median(values),
                p95=percentile(values, 95), min=min(values), max=max(values))


def analyze(folder, expected_frames=None):
    folder = pathlib.Path(folder)
    with (folder / "TrackingStates.csv").open() as stream:
        states = list(csv.DictReader(stream))
    with (folder / "TrackingTimeStats.txt").open() as stream:
        header = next(stream).lstrip("#").strip().split(",")
        times = list(csv.reader(stream))
    if header[2].strip() != "ORB ext[ms]" or header[8].strip() != "Total[ms]":
        raise RuntimeError("Unexpected tracking timing schema")
    if len(states) != len(times) or not times:
        raise RuntimeError("State/timing row count differs or no timing rows")
    if expected_frames is not None and len(times) != expected_frames:
        raise RuntimeError("Processed frame count differs from official input count")
    frames = []
    for index, (state, timing) in enumerate(zip(states, times)):
        if int(state["frame_index"]) != index or len(timing) != len(FIELDS):
            raise RuntimeError("Frame indexing or timing column mismatch")
        numbers = list(map(float, timing))
        if not all(math.isfinite(value) and value >= 0 for value in numbers):
            raise RuntimeError("Non-finite or negative frame timing")
        if not numbers[8] >= numbers[2] > 0:
            raise RuntimeError("ORB timing is not positive or exceeds Total")
        kind = category(int(state["state_before"]), int(state["state_after"]))
        frame = dict(state, category=kind, **dict(zip(FIELDS, numbers)))
        frame["orb_ratio"] = numbers[2]/numbers[8] if kind == "normal" else ""
        frames.append(frame)
    with (folder / "frames.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(frames[0]))
        writer.writeheader()
        writer.writerows(frames)
    summary = []
    modules = []
    for kind in ("normal", "initialization", "lost", "all_frames"):
        selected = frames if kind == "all_frames" else [frame for frame in frames if frame["category"] == kind]
        total = describe([frame["total_ms"] for frame in selected])
        orb = describe([frame["orb_ms"] for frame in selected])
        result = dict(category=kind, frames=len(selected), total_mean_ms=total["mean"],
                      total_median_ms=total["median"], total_p95_ms=total["p95"],
                      orb_mean_ms=orb["mean"], orb_median_ms=orb["median"], orb_p95_ms=orb["p95"],
                      orb_ratio_frame_median="", orb_ratio_sums="", total_gt50_fraction="", total_gt33_fraction="")
        if kind == "normal" and selected:
            result.update(orb_ratio_frame_median=statistics.median(frame["orb_ratio"] for frame in selected),
                          orb_ratio_sums=sum(frame["orb_ms"] for frame in selected)/sum(frame["total_ms"] for frame in selected),
                          total_gt50_fraction=sum(frame["total_ms"] > 50 for frame in selected)/len(selected),
                          total_gt33_fraction=sum(frame["total_ms"] > 33 for frame in selected)/len(selected))
        summary.append(result)
        for name in FIELDS[:-1]:
            values = [frame[name] for frame in selected if frame[name] > 0]
            modules.append(dict(category=kind, module=name, excluded_zero=len(selected)-len(values), **describe(values)))
    for name, rows in (("timing_summary.csv", summary), ("module_summary.csv", modules)):
        with (folder / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    session = (folder / "SessionInfo.txt").read_text()
    match = re.search(r"^Number of Maps: (\d+)$", session, re.MULTILINE)
    if not match:
        raise RuntimeError("Final Atlas map count missing")
    log = (folder / "program.log").read_text(errors="replace") if (folder / "program.log").exists() else ""
    normal = next(row for row in summary if row["category"] == "normal")
    facts = dict(normal, processed_frames=len(frames), maps=int(match.group(1)),
                 initialization_frames=sum(frame["category"] == "initialization" for frame in frames),
                 lost_frames=sum(frame["category"] == "lost" for frame in frames),
                 recovery_frames=sum(int(frame["state_before"]) in (3, 4) and int(frame["state_after"]) == 2 for frame in frames),
                 active_map_resets=len(re.findall(r"^Active map Reseting\s*$", log, re.MULTILINE)),
                 full_resets=len(re.findall(r"^System Reseting\s*$", log, re.MULTILINE)))
    (folder / "timing_facts.json").write_text(json.dumps(facts, indent=2))
    return facts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--expected-frames", type=int)
    args = parser.parse_args()
    facts = analyze(args.folder, args.expected_frames)
    print("A2_TIMING_PASS frames=%d normal=%d init=%d lost=%d recovery=%d maps=%d" %
          (facts["processed_frames"], facts["frames"], facts["initialization_frames"],
           facts["lost_frames"], facts["recovery_frames"], facts["maps"]))
