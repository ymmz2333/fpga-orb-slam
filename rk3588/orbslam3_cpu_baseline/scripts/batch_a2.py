#!/usr/bin/env python3
"""PC orchestrator: durable board attempts, LAN copy, PC evo evaluation."""
import argparse
import base64
import csv
import datetime
import json
import pathlib
import statistics
import subprocess
import sys
import shlex

ROOT = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--cooling-note", required=True)
parser.add_argument("--dataset", required=True, help="Extracted MH01 on the PC")
parser.add_argument("--numpy-only", action="store_true")
parser.add_argument("--batch", default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S"))
parser.add_argument("--summarize-only", action="store_true")
parser.add_argument("--resume", action="store_true", help="Resume evaluated attempts; never repeat a live job")
args = parser.parse_args()
if not args.batch or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in args.batch):
    raise SystemExit("Invalid batch ID")
batch = ROOT / "runtime/a2" / args.batch
report = ROOT / "reports/a2" / args.batch
report.mkdir(parents=True, exist_ok=True)
rows = []


def refresh():
    records = []
    for folder in sorted(batch.glob("attempt_*")):
        record = dict(attempt=folder.name, output=str(folder), configuration="official_600x350_1000features_8levels",
                      tracking_width=600, tracking_height=350, resize_policy="official nonuniform resize",
                      status="未完成", reason="", valid_run=False)
        meta_path = folder / "run_metadata.json"
        if not meta_path.exists():
            record["reason"] = "metadata missing"
            records.append(record)
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        record.update(process_status=meta["status"], exit_code=meta["exit_code"],
                      frequency_drop=meta["frequency_drop_detected"], thermal_cap=meta["thermal_cap_detected"])
        if meta["status"] == "FINISHED" and (folder / "ate.json").exists() and (folder / "timing_facts.json").exists():
            record.update(json.loads((folder / "ate.json").read_text()))
            record.update(json.loads((folder / "timing_facts.json").read_text()))
            affected = meta["frequency_drop_detected"] or meta["thermal_cap_detected"]
            record.update(status="降频需补跑" if affected else "完成", valid_run=not affected,
                          reason="frequency drop / thermal cap" if affected else "")
        else:
            record["reason"] = meta.get("error", "Timing/ATE evaluation not complete; inspect logs")
        telemetry = folder / "telemetry.csv"
        if telemetry.exists():
            with telemetry.open() as stream:
                samples = list(csv.DictReader(stream))
            temps = [float(sample["thermal_zone0_temp_mc"])/1000 for sample in samples if "thermal_zone0_temp_mc" in sample]
            record["mean_soc_temp_c"] = statistics.mean(temps) if temps else ""
            record["max_soc_temp_c"] = max(temps) if temps else ""
            all_temps = [float(value)/1000 for sample in samples for name, value in sample.items() if name.endswith('_temp_mc')]
            record["max_all_zones_temp_c"] = max(all_temps) if all_temps else ""
            for policy in ("policy4", "policy6"):
                freq = [int(sample[policy+"_cur_khz"]) for sample in samples if policy+"_cur_khz" in sample]
                record[policy+"_freq_min_khz"] = min(freq) if freq else ""
                record[policy+"_freq_max_khz"] = max(freq) if freq else ""
        records.append(record)
    if records:
        fields = list(dict.fromkeys(key for row in records for key in row))
        with (report / "runs.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
    valid = [record for record in records if record["valid_run"]]
    summary = []
    for key in ("ate_rmse_m", "total_mean_ms", "total_median_ms", "total_p95_ms", "orb_median_ms", "orb_p95_ms",
                "orb_ratio_frame_median", "orb_ratio_sums", "total_gt50_fraction", "total_gt33_fraction", "mean_soc_temp_c"):
        values = [float(row[key]) for row in valid if row.get(key, "") != ""]
        if values:
            summary.append(dict(configuration="A2 official nonuniform resize", tracking_width=600, tracking_height=350,
                                metric=key, valid_runs=len(values), median=statistics.median(values), min=min(values), max=max(values)))
    with (report / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["configuration", "tracking_width", "tracking_height", "metric", "valid_runs", "median", "min", "max"])
        writer.writeheader()
        writer.writerows(summary)
    return records, valid


if args.summarize_only:
    records, valid = refresh()
    print("A2_SUMMARY attempts=%d valid=%d" % (len(records), len(valid)))
    raise SystemExit(0)
if batch.exists() and not args.resume:
    raise SystemExit("Refusing to rerun existing batch; use --summarize-only or a new batch ID")
board = json.loads((ROOT / "local_board.json").read_text())
alias = board.get("sshAlias", "rk3588")
remote_root = board.get("remoteRoot", "~/orbslam3_cpu_baseline")
if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for c in alias) or alias.startswith("-"):
    raise SystemExit("Unsafe SSH alias")
if not remote_root.startswith(("~/", "/")) or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./~" for c in remote_root):
    raise SystemExit("Unsafe remote root")
from validate_mh01 import validate
dataset = validate(args.dataset, ROOT / "reports/a2/MH01.txt")
if not args.numpy_only and not (pathlib.Path(sys.executable).parent / "evo_ape.exe").exists():
    raise SystemExit("PC evo missing; install it or explicitly use --numpy-only")
batch.mkdir(parents=True, exist_ok=args.resume)
def remote_request(request):
    payload = base64.b64encode(json.dumps(request, ensure_ascii=False).encode("utf-8")).decode("ascii")
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", alias,
                             "python3 "+remote_root+"/scripts/remote_job.py request "+payload],
                            capture_output=True, text=True, encoding="utf-8", timeout=75)
    with (batch / "controller.log").open("a", encoding="utf-8") as log:
        log.write(result.stdout+result.stderr)
    if "SSH_WORKFLOW_ERROR" in result.stdout or not result.stdout:
        raise RuntimeError("SSH controller failed; inspect controller.log")
    return result


records, valid = refresh()
if len(valid) >= 5:
    raise SystemExit("Already has five valid runs; use --summarize-only")
if args.resume and any(record['status'] == '未完成' for record in records):
    raise SystemExit("Resume requires all existing attempts to be evaluated; inspect their jobs/logs first")
for attempt in range(len(records)+1, 11):
    folder = batch / ("attempt_%02d" % attempt)
    remote_folder = "runtime/a2/"+args.batch+"/"+folder.name
    command = "python3 scripts/run_a2.py --output "+shlex.quote(remote_folder)+" --cooling-note "+shlex.quote(args.cooling_note)
    result = remote_request(dict(action="start", value=command, name="a2-"+folder.name))
    job_id = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("job_id="))
    print("A2_STARTED attempt=%d job_id=%s" % (attempt, job_id), flush=True)
    while True:
        result = remote_request(dict(action="wait", value=job_id, seconds=30))
        state = next(line for line in result.stdout.splitlines() if line.startswith("status="))
        print("A2_PROGRESS attempt=%d %s" % (attempt, state), flush=True)
        if "RUNNING" not in state and "STARTING" not in state:
            break
    subprocess.run(["scp", "-q", "-r", alias+":"+remote_root+"/"+remote_folder, str(batch)], check=True)
    (folder / "remote_job_id.txt").write_text(job_id)
    if result.returncode or "SUCCEEDED" not in state:
        refresh()
        raise SystemExit("Attempt failed; stop for diagnosis, not continued blind retries")
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts/analyze_a2.py"), str(folder),
                        "--expected-frames", str(dataset["frames"])], check=True)
        evaluate_command = [sys.executable, str(ROOT / "scripts/evaluate_a2.py"), str(folder), "--dataset", args.dataset]
        if args.numpy_only:
            evaluate_command.append("--numpy-only")
        subprocess.run(evaluate_command, check=True)
    except subprocess.CalledProcessError:
        refresh()
        raise SystemExit("Timing/trajectory evaluation failed; inspect this attempt")
    records, valid = refresh()
    print("A2_PROGRESS attempt=%d valid=%d/5" % (attempt, len(valid)), flush=True)
    if float(records[-1]["ate_rmse_m"]) > 0.10:
        raise SystemExit("ATE RMSE above 0.10 m diagnostic gate; investigate input/build/reference before more runs")
    if len(valid) >= 5:
        print("A2_FIVE_VALID_RUNS_COMPLETE report="+str(report))
        break
else:
    raise SystemExit("No five valid runs after ten attempts; resolve cooling/frequency behavior")
