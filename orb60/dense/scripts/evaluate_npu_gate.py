"""Numerical gate: no affine/min-max fitting may hide conversion errors."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr


def evaluate(reference, output):
    reference = np.asarray(reference, dtype=np.float64).ravel()
    output = np.asarray(output, dtype=np.float64).ravel()
    if output.shape != reference.shape or not np.isfinite(output).all():
        raise ValueError("Invalid board output shape/values")
    span = float(np.quantile(reference, .95) - np.quantile(reference, .05))
    if span <= 1e-8 or not np.isfinite(reference).all():
        raise ValueError("Degenerate floating reference")
    return dict(normalized_rmse=float(np.sqrt(np.mean((output - reference) ** 2)) / span),
                spearman=float(spearmanr(reference, output).statistic),
                normalization="RMSE / (reference P95 - P05), no output alignment")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--samples", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--board", type=Path, required=True)
    a = p.parse_args()
    samples = json.loads((a.samples / "samples.json").read_text())
    board = json.loads((a.board / "worker.json").read_text())
    if len(samples["frames"]) != 20 or len(board["frames"]) != 20:
        raise ValueError("Gate requires exactly 20 completed indoor inputs")
    if [f["id"] for f in samples["frames"]] != [f["id"] for f in board["frames"]]:
        raise ValueError("Board frame ordering mismatch")
    metrics = []
    for frame in samples["frames"]:
        name = frame["id"]
        value = np.load(a.samples / (name + ".input.npy"))
        if hashlib.sha256(value.tobytes()).hexdigest() != frame["input_sha256"]:
            raise ValueError("Input provenance mismatch")
        result = evaluate(np.load(a.reference / (name + ".reference.npy")),
                          np.fromfile(a.board / (name + ".output.f32"), dtype="<f4"))
        result["id"] = name
        result["passed"] = result["normalized_rmse"] <= .03 and result["spearman"] >= .98
        metrics.append(result)
    # Placement must be reviewed from actual operator-profile, not inferred from SDK init.
    report = dict(status="NUMERICAL_PASS_PLACEMENT_REVIEW_REQUIRED" if all(x["passed"] for x in metrics) else "FAILED",
                  frames=metrics, worst_nrmse=max(x["normalized_rmse"] for x in metrics),
                  minimum_spearman=min(x["spearman"] for x in metrics),
                  runtime=board["runtime"], driver=board["driver"],
                  operator_profile="operator-profile.txt")
    (a.board / "numerical-gate.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "frames"}, indent=2))
    if report["status"] == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
