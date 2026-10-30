"""Combine numerical, placement and durable board completion evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--attempt", type=Path, required=True)
    p.add_argument("--model", choices=["da2-small", "midas-v21-small"], required=True)
    a = p.parse_args()
    board = a.attempt / "board"
    numerical = json.loads((board / "numerical-gate.json").read_text())
    worker = json.loads((board / "worker.json").read_text())
    job = json.loads((board / "job-state.json").read_text())
    profile = (board / "operator-profile.txt").read_text()
    rows = [dict(id=int(m[1]), op=m[2], dtype=m[3], target=m[4], full=line)
            for line in profile.splitlines()
            if (m := re.match(r"^\s*(\d+)\s+(\w+)\s+(\w+)\s+(NPU|CPU|GPU)\s+", line))]
    allowed_cpu = {"InputOperator", "OutputOperator", "Resize"}
    cpu = [r for r in rows if r["target"] != "NPU"]
    prohibited = [r for r in cpu if r["op"] not in allowed_cpu]
    compute_npu = [r for r in rows if r["target"] == "NPU" and
                   r["op"] not in {"InputOperator", "OutputOperator", "Reshape", "Transpose"}]
    passed = (numerical["status"] == "NUMERICAL_PASS_PLACEMENT_REVIEW_REQUIRED" and
              job["status"] == "SUCCEEDED" and job["exit_code"] == 0 and
              len(worker["frames"]) == 20 and len(compute_npu) >= 20 and
              all(f["hardware_run_us"] > 0 for f in worker["frames"]) and not prohibited)
    report = dict(status="PASS" if passed else "FAILED", model=a.model,
                  numerical_status=numerical["status"], worst_nrmse=numerical["worst_nrmse"],
                  minimum_spearman=numerical["minimum_spearman"],
                  npu_compute_nodes=len(compute_npu), cpu_nodes=cpu,
                  prohibited_cpu_nodes=prohibited, runtime=worker["runtime"], driver=worker["driver"],
                  mean_seconds=sum(f["seconds"] for f in worker["frames"]) / 20,
                  peak_rss_kib=worker["peak_rss_kib"],
                  model_sha256=hashlib.sha256((a.attempt/"depth.rknn").read_bytes()).hexdigest(),
                  operator_profile_sha256=hashlib.sha256((board/"operator-profile.txt").read_bytes()).hexdigest(),
                  board_job=job)
    (a.attempt / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k not in {"cpu_nodes","board_job"}}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
