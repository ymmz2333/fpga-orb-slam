#!/usr/bin/env python3
"""Durable RK3588 shell jobs with bounded, reconnectable diagnostics (Python 3.8+)."""
import base64
import collections
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
JOBS = ROOT / "runtime/ssh_jobs"
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,96}\Z")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
FINAL = {"SUCCEEDED", "FAILED"}


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def location(job_id):
    if not ID_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    return JOBS / job_id


def save(folder, state):
    temporary = folder / ("state.%d.tmp" % os.getpid())
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(temporary), str(folder / "state.json"))


def process_identity(pid):
    try:
        fields = pathlib.Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def state_of(folder):
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    if state["status"] not in FINAL:
        pid = state.get("worker_pid")
        if pid and process_identity(pid) != state.get("worker_identity"):
            state["status"] = "LOST"
            state["detail"] = "Worker disappeared; no trustworthy exit code. Inspect the log."
        elif not pid and time.time() - state["created_epoch"] > 10:
            state["status"] = "LOST"
            state["detail"] = "Worker did not start; no trustworthy exit code."
    return state


def worker(job_id):
    folder = location(job_id)
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    state.update(status="RUNNING", started_utc=utc(), worker_pid=os.getpid(),
                 worker_identity=process_identity(os.getpid()))
    save(folder, state)
    env = os.environ.copy()
    for key, prefix in (("LD_LIBRARY_PATH", ROOT / "install/lib"),
                        ("CMAKE_PREFIX_PATH", ROOT / "install")):
        env[key] = str(prefix) + (":" + env[key] if env.get(key) else "")
    try:
        with (folder / "output.log").open("ab", buffering=0) as log:
            result = subprocess.run(["bash", "-lc", state["command"]], cwd=str(ROOT),
                                    env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        state.update(exit_code=result.returncode,
                     status="SUCCEEDED" if result.returncode == 0 else "FAILED")
    except Exception as error:
        state.update(status="FAILED", exit_code=125, detail=str(error))
    state["finished_utc"] = utc()
    save(folder, state)


def start(command, name):
    if not command.strip():
        raise ValueError("Command is empty")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
        raise ValueError("Name must be 1-32 letters, digits, '-' or '_'")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    job_id = "%s-%s-%s" % (stamp, name, uuid.uuid4().hex[:8])
    folder = location(job_id)
    folder.mkdir(parents=True)
    save(folder, dict(job_id=job_id, status="STARTING", command=command,
                      cwd=str(ROOT), created_utc=utc(), created_epoch=time.time(), exit_code=None))
    # The worker owns its log/exit record and survives SSH disconnection.
    with (folder / "worker.log").open("ab", buffering=0) as log:
        subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "worker", job_id],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True, close_fds=True)
    return folder


def wait_for(folder, seconds):
    deadline = time.monotonic() + seconds
    while True:
        state = state_of(folder)
        if state["status"] in FINAL or state["status"] == "LOST" or time.monotonic() >= deadline:
            return state
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))


def log_excerpt(folder, lines, max_chars, pattern="", scan_bytes=65536):
    file = folder / "output.log"
    if not file.exists():
        return "(log not created yet)"
    matcher = re.compile(pattern, re.IGNORECASE) if pattern else None
    with file.open("rb") as stream:
        size = file.stat().st_size
        offset = max(0, size - scan_bytes)
        stream.seek(offset)
        raw = stream.read(scan_bytes).decode("utf-8", errors="replace").replace("\r", "\n")
    if offset:
        # Skip a partial first line, but retain useful tail text for huge single lines.
        remainder = raw.partition("\n")[2]
        raw = remainder if remainder.strip() else "...[partial long line] " + raw[-350:]
    selected = collections.deque(maxlen=lines)
    for line in ANSI.sub("", raw).splitlines():
        if line.strip() and (matcher is None or matcher.search(line)):
            selected.append(line[:400] + (" ...[line truncated]" if len(line) > 400 else ""))
    excerpt = "\n".join(selected) or "(no matching lines in scanned tail)"
    if len(excerpt) > max_chars:
        excerpt = "...[excerpt truncated]\n" + excerpt[-max(0, max_chars - 30):]
    return "log_bytes=%d scan_tail_bytes=%d\n%s" % (size, min(size, scan_bytes), excerpt)


def summary(folder, state, lines=4, max_chars=1200):
    print("job_id=" + state["job_id"])
    print("status=%s exit_code=%s" % (state["status"], state.get("exit_code")))
    print("cwd=" + state["cwd"])
    print("log=" + str(folder / "output.log"))
    if state.get("detail"):
        print("detail=" + state["detail"][:300])
    if lines:
        print(log_excerpt(folder, lines, max_chars))


def bounded_int(request, key, default, low, high):
    value = int(request.get(key, default))
    if not low <= value <= high:
        raise ValueError("%s must be between %d and %d" % (key, low, high))
    return value


def dispatch(request):
    action = request["action"]
    seconds = bounded_int(request, "seconds", 30, 0, 60)
    lines = bounded_int(request, "lines", 20, 1, 100)
    max_chars = bounded_int(request, "max_chars", 4000, 200, 12000)
    if action == "check":
        print("SSH_WORKFLOW_OK")
        print("hostname=" + os.uname().nodename)
        print("root=" + str(ROOT))
        print("python=" + sys.version.split()[0])
        return 0
    if action == "list":
        states = [state_of(file.parent) for file in sorted(JOBS.glob("*/state.json"), reverse=True)]
        active = [state for state in states if state["status"] not in FINAL]
        completed = [state for state in states if state["status"] in FINAL]
        for state in (active + completed)[:8]:
            print("%s %s exit=%s" % (state["job_id"], state["status"], state.get("exit_code")))
        if len(states) > 8:
            print("showing=8 total=%d unfinished=%d (unfinished first)" % (len(states), len(active)))
        if not states:
            print("(no jobs)")
        return 0
    if action in ("start", "exec"):
        folder = start(request["value"], request.get("name", "task"))
        state = wait_for(folder, seconds if action == "exec" else 0)
    else:
        folder = location(request["value"])
        if action == "log":
            scan_bytes = bounded_int(request, "scan_bytes", 1048576, 1024, 16777216)
            print("job_id=" + folder.name)
            print(log_excerpt(folder, lines, max_chars, request.get("match", ""), scan_bytes))
            return 0
        if action not in ("status", "wait"):
            raise ValueError("Unknown action")
        state = wait_for(folder, seconds if action == "wait" else 0)
    summary(folder, state)
    if action in ("exec", "wait", "status"):
        if state["status"] == "FAILED":
            code = state["exit_code"]
            return code if 1 <= code <= 255 else 1
        if state["status"] == "LOST":
            return 3
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "worker":
            worker(sys.argv[2])
            sys.exit(0)
        if len(sys.argv) != 3 or sys.argv[1] != "request":
            raise ValueError("Use: remote_job.py request <base64-JSON>")
        payload = base64.b64decode(sys.argv[2], validate=True).decode("utf-8")
        sys.exit(dispatch(json.loads(payload)))
    except Exception as error:
        print("SSH_WORKFLOW_ERROR: " + str(error)[:500], file=sys.stderr)
        sys.exit(2)
