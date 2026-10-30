#!/usr/bin/env python3
"""Run bounded, real SSH acceptance checks; retain a compact CSV (no SLAM work)."""
import argparse
import csv
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--powershell", default="powershell")
args = parser.parse_args()
results = []


def call(action, value=None, **options):
    command = [args.powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts/rk.ps1"), "-Action", action]
    if value is not None:
        command.extend(["-Value", value])
    for name, value in options.items():
        command.extend(["-" + name, str(value)])
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          encoding="utf-8", errors="replace", timeout=75)


def job_id(output):
    match = re.search(r"^job_id=(\S+)$", output, re.MULTILINE)
    if not match:
        raise AssertionError("No job ID: " + output[-1200:])
    return match.group(1)


def check(name, condition, detail):
    results.append([name, "PASS" if condition else "FAIL", detail])
    print(name + ": " + results[-1][1], flush=True)


result = call("check")
check("key_alias_and_workspace", result.returncode == 0 and "SSH_WORKFLOW_OK" in result.stdout,
      "native SSH alias, batch authentication, board Python helper")

result = call("exec", "printf '%s\\n' 'literal $HOME `backtick` and 中文'; pwd", Name="verify-quoting")
check("quoting_unicode_and_cwd", result.returncode == 0 and
      "literal $HOME `backtick` and 中文" in result.stdout and "/home/cat/orbslam3_cpu_baseline" in result.stdout,
      "payload preserves literal shell characters; board root is cwd")

result = call("exec", "seq 1 10000", Name="verify-output")
large_job = job_id(result.stdout)
check("large_output_bounded", result.returncode == 0 and len(result.stdout) < 2000 and "10000" in result.stdout,
      "10,000 log lines stored remotely; default reply below 2,000 characters")
result = call("exec", "test $(wc -l < runtime/ssh_jobs/%s/output.log) -eq 10000" % large_job,
              Name="verify-retention")
check("complete_log_retained", result.returncode == 0 and "status=SUCCEEDED" in result.stdout,
      "remote raw log has exactly 10,000 lines")
result = call("log", large_job, Lines=3, MaxChars=200)
check("bounded_log_request", result.returncode == 0 and len(result.stdout) < 500 and "10000" in result.stdout,
      "explicit tail request obeys line/character limits")

result = call("exec", "python3 -c 'print(chr(120)*100000 + chr(84)+chr(65)+chr(73)+chr(76))'",
              Name="verify-long-line")
check("huge_single_line_tail", result.returncode == 0 and len(result.stdout) < 2000 and "TAIL" in result.stdout,
      "100,005-byte single-line log keeps its final marker in a bounded excerpt")

result = call("exec", "printf '%s\\n' 'compiler error: SSH acceptance sentinel' >&2; exit 7", Name="verify-failure")
failed_job = job_id(result.stdout)
check("failure_exit_propagated", result.returncode == 7 and "status=FAILED exit_code=7" in result.stdout,
      "real shell failure remains failed and propagates exit code 7")
result = call("log", failed_job, Match="compiler error", Lines=3)
check("failure_diagnostic_filter", result.returncode == 0 and "SSH acceptance sentinel" in result.stdout,
      "bounded regex-filtered diagnostic excerpt")

result = call("start", "sleep 8; printf '%s\\n' reconnect-complete", Name="verify-detached")
detached_job = job_id(result.stdout)
check("detached_start", result.returncode == 0 and "status=SUCCEEDED" not in result.stdout,
      "start returns a live job, without claiming completion")
result = call("wait", detached_job, Seconds=1)
check("wait_timeout_preserves_running", result.returncode == 0 and
      ("status=RUNNING" in result.stdout or "status=STARTING" in result.stdout),
      "bounded wait expiry does not mark job successful")
result = call("wait", detached_job, Seconds=15)
check("reconnect_final_exit", result.returncode == 0 and "status=SUCCEEDED exit_code=0" in result.stdout and
      "reconnect-complete" in result.stdout,
      "worker completes after launching SSH connection closes; new connection reads true exit")

result = call("exec", "sleep 5; printf '%s\\n' foreground-complete", Name="verify-exec-timeout", Seconds=0)
waiting_job = job_id(result.stdout)
check("exec_timeout_retains_job", result.returncode == 0 and "status=SUCCEEDED" not in result.stdout,
      "foreground wait expiry returns the durable job ID")
result = call("wait", waiting_job, Seconds=15)
check("exec_timeout_final_exit", result.returncode == 0 and "foreground-complete" in result.stdout,
      "timed-out client wait did not kill the remote command")

result = call("status", "../invalid")
check("job_path_validation", result.returncode == 2 and "Invalid job ID" in result.stdout,
      "reject directory traversal")
out = ROOT / "reports/ssh_workflow"
out.mkdir(parents=True, exist_ok=True)
with (out / "acceptance.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["check", "status", "detail"])
    writer.writerows(results)
if any(row[1] != "PASS" for row in results):
    raise SystemExit("SSH_WORKFLOW_ACCEPTANCE_FAILED; inspect reports/ssh_workflow/acceptance.csv")
print("SSH_WORKFLOW_ACCEPTANCE_PASS")
