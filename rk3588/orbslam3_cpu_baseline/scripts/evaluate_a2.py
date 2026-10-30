#!/usr/bin/env python3
"""PC-side camera-reference ATE: evo Sim3, independently checked with NumPy."""
import argparse
import csv
import decimal
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import zipfile

import numpy as np
import yaml
from scipy.spatial.transform import Rotation

ROOT = pathlib.Path(__file__).resolve().parent.parent


def umeyama(reference, estimate):
    """Fit reference = scale * R * estimate + t; reject deficient geometry."""
    reference, estimate = np.asarray(reference), np.asarray(estimate)
    if reference.shape != estimate.shape or reference.ndim != 2 or reference.shape[1] != 3 or len(reference) < 3:
        raise RuntimeError("At least three paired 3D positions required")
    centered_x = estimate-estimate.mean(axis=0)
    centered_y = reference-reference.mean(axis=0)
    covariance = centered_y.T @ centered_x / len(reference)
    u, singular, vt = np.linalg.svd(covariance)
    if np.count_nonzero(singular > np.finfo(float).eps) < 2:
        raise RuntimeError("Degenerate trajectory for Sim3 alignment")
    sign = np.eye(3)
    if np.linalg.det(u)*np.linalg.det(vt) < 0:
        sign[2, 2] = -1
    rotation = u @ sign @ vt
    scale = np.sum(singular * np.diag(sign)) / np.mean(np.sum(centered_x**2, axis=1))
    translation = reference.mean(axis=0)-scale*rotation @ estimate.mean(axis=0)
    errors = np.linalg.norm(reference-(scale*(rotation @ estimate.T).T+translation), axis=1)
    return dict(scale=float(scale), rotation=rotation.tolist(), translation=translation.tolist()), errors


def associate(reference_stamps, estimate_stamps, maximum=0.01):
    # Same shorter-to-longer nearest-time policy as evo.core.sync (no dedup).
    reference_stamps = np.asarray(reference_stamps)
    estimate_stamps = np.asarray(estimate_stamps)
    if len(reference_stamps) < len(estimate_stamps):
        small, large, switched = reference_stamps, estimate_stamps, False
    else:
        small, large, switched = estimate_stamps, reference_stamps, True
    a, b = [], []
    for index, stamp in enumerate(small):
        nearest = int(np.argmin(np.abs(large-stamp)))
        if abs(large[nearest]-stamp) <= maximum:
            a.append(index)
            b.append(nearest)
    return (np.array(b, dtype=int), np.array(a, dtype=int)) if switched else (np.array(a, dtype=int), np.array(b, dtype=int))


def convert(folder, dataset):
    raw = folder / "f_MH01.txt"
    truth = dataset / "mav0/state_groundtruth_estimate0/data.csv"
    calibration = dataset / "mav0/cam0/sensor.yaml"
    inputs = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (raw, truth, calibration)}
    with raw.open() as source, (folder / "camera.tum").open("w") as target:
        poses = 0
        for line in source:
            fields = line.split()
            if not fields or fields[0].startswith("#"):
                continue
            if len(fields) != 8 or decimal.Decimal(fields[0]) < 10**17:
                raise RuntimeError("Expected nanosecond EuRoC camera trajectory")
            fields[0] = format(decimal.Decimal(fields[0])/decimal.Decimal(10**9), ".9f")
            target.write(" ".join(fields)+"\n")
            poses += 1
    if not poses:
        raise RuntimeError("Empty camera trajectory; ATE unfinished")
    matrix = np.asarray(yaml.safe_load(calibration.read_text())["T_BS"]["data"]).reshape(4, 4)
    if not np.allclose(matrix[3], [0, 0, 0, 1]) or not np.allclose(matrix[:3,:3].T@matrix[:3,:3], np.eye(3), atol=1e-5):
        raise RuntimeError("Invalid cam0 T_BS rigid transform")
    with truth.open() as source, (folder / "groundtruth_body.tum").open("w") as body, (folder / "groundtruth_cam0.tum").open("w") as camera:
        for fields in csv.reader(source):
            if not fields or fields[0].lstrip().startswith("#"):
                continue
            stamp = format(decimal.Decimal(fields[0])/decimal.Decimal(10**9), ".9f")
            position = np.asarray(list(map(float, fields[1:4])))
            q_body = np.asarray(list(map(float, [fields[5], fields[6], fields[7], fields[4]])))
            rotation = Rotation.from_quat(q_body).as_matrix()
            camera_position = position + rotation@matrix[:3,3]
            q_camera = Rotation.from_matrix(rotation@matrix[:3,:3]).as_quat()
            body.write(stamp+" "+" ".join("%.12f" % value for value in list(position)+list(q_body))+"\n")
            camera.write(stamp+" "+" ".join("%.12f" % value for value in list(camera_position)+list(q_camera))+"\n")
    return inputs, poses


def evaluate(folder, dataset, numpy_only=False):
    folder, dataset = pathlib.Path(folder).resolve(), pathlib.Path(dataset).resolve()
    inputs, poses = convert(folder, dataset)
    reference = np.atleast_2d(np.loadtxt(folder / "groundtruth_cam0.tum"))
    estimate = np.atleast_2d(np.loadtxt(folder / "camera.tum"))
    if not np.all(np.isfinite(reference)) or not np.all(np.isfinite(estimate)):
        raise RuntimeError("Nonfinite trajectory")
    for trajectory in (reference, estimate):
        if np.any(np.diff(trajectory[:, 0]) < 0):
            raise RuntimeError("Trajectory timestamps go backwards")
        repeats = np.where(np.diff(trajectory[:, 0]) == 0)[0]
        if any(not np.array_equal(trajectory[index], trajectory[index+1]) for index in repeats):
            raise RuntimeError("Same timestamp has different poses")
    duplicate_rows = int(np.count_nonzero(np.diff(estimate[:, 0]) == 0))
    ri, ei = associate(reference[:, 0], estimate[:, 0])
    alignment, errors = umeyama(reference[ri, 1:4], estimate[ei, 1:4])
    numpy_rmse = float(np.sqrt(np.mean(errors**2)))
    method, rmse = "NumPy Umeyama Sim3 (temporary; evo cross-check pending)", numpy_rmse
    if not numpy_only:
        saved = folder / "ape.zip"
        manifest = folder / "ape_inputs.json"
        if saved.exists():
            recorded = json.loads(manifest.read_text()) if manifest.exists() else {}
            # Moving retained evidence changes paths, not the identity of the three inputs.
            if len(recorded) != len(inputs) or sorted(recorded.values()) != sorted(inputs.values()):
                raise RuntimeError("Existing evo result has different / unrecorded inputs")
        else:
            env = dict(os.environ, MPLBACKEND="Agg")
            evo_ape = pathlib.Path(sys.executable).parent / ("evo_ape.exe" if os.name == "nt" else "evo_ape")
            command = [str(evo_ape), "tum", str(folder / "groundtruth_cam0.tum"), str(folder / "camera.tum"),
                       "-as", "--t_max_diff", "0.01", "--save_results", str(saved)]
            (folder / "evo_command.json").write_text(json.dumps(command, indent=2))
            with (folder / "evo.log").open("w") as log:
                subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=True)
            manifest.write_text(json.dumps(inputs, indent=2))
        with zipfile.ZipFile(saved) as archive:
            stats = json.loads(archive.read("stats.json"))
            evo_errors = np.load(io.BytesIO(archive.read("error_array.npy")), allow_pickle=False)
        rmse = float(stats["rmse"])
        if len(evo_errors) != len(errors) or not np.allclose(evo_errors, errors, rtol=1e-7, atol=1e-9):
            raise RuntimeError("Independent NumPy errors disagree with evo")
        if not np.isclose(np.sqrt(np.mean(evo_errors**2)), rmse):
            raise RuntimeError("evo RMSE disagrees with saved errors")
        import evo
        method = "evo "+evo.__version__+" Sim3; NumPy cross-check passed"
    with (folder / "ape_errors.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["estimate_timestamp_s", "reference_timestamp_s", "absolute_error_m"])
        writer.writerows(zip(estimate[ei, 0], reference[ri, 0], errors))
    (folder / "sim3.json").write_text(json.dumps(alignment, indent=2))
    result = dict(ate_rmse_m=rmse, numpy_rmse_m=numpy_rmse, associated_poses=len(errors), exported_poses=poses,
                  duplicate_export_rows=duplicate_rows, duplicate_policy="Preserve identical upstream rows; evo-compatible weighting",
                  evaluation_method=method, alignment="Sim3", timestamp_unit="seconds",
                  reference="cam0: T_world_body * T_body_cam0", max_time_difference_s=0.01)
    (folder / "ate.json").write_text(json.dumps(result, indent=2))
    with (folder / "ate.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result))
        writer.writeheader()
        writer.writerow(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--numpy-only", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.folder, args.dataset, args.numpy_only)
    print("A2_ATE rmse_m=%.9f associated=%d exported=%d %s" %
          (result["ate_rmse_m"], result["associated_poses"], result["exported_poses"], result["evaluation_method"]))
