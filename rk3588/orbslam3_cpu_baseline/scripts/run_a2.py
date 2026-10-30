#!/usr/bin/env python3
"""One real-time MH01 attempt, A76-only SLAM and sampled thermal/frequency evidence."""
import argparse
import csv
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import signal
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--cooling-note", required=True)
parser.add_argument("--dataset", default=str(pathlib.Path.home() / "data/euroc/MH_01_easy"))
parser.add_argument("--settings", help="Separate YAML for a parameter-matrix run; A2 default unchanged")
parser.add_argument("--stop-on-frequency-drop", action="store_true")
parser.add_argument("--feature-mode", choices=("native", "dump", "inject"))
parser.add_argument("--feature-dir")
parser.add_argument("--dmc-performance", action="store_true")
parser.add_argument("--timestamps", help="Prepared input timestamp file; default remains official MH01")
parser.add_argument("--sequence", default="MH01")
parser.add_argument("--dataset-kind", choices=("euroc","prepared"), default="euroc")
args = parser.parse_args()
output = pathlib.Path(args.output).resolve()
if output.exists():
    raise SystemExit("Refusing to reuse run output: " + str(output))
output.mkdir(parents=True)
source = ROOT / "vendor/ORB_SLAM3"
settings = pathlib.Path(args.settings).resolve() if args.settings else source / "Examples/Monocular/EuRoC.yaml"
dataset = pathlib.Path(args.dataset).expanduser().resolve()
timestamps = (pathlib.Path(args.timestamps).expanduser().resolve() if args.timestamps else
              source / "Examples/Monocular/EuRoC_TimeStamps/MH01.txt")
policies = sorted(pathlib.Path("/sys/devices/system/cpu/cpufreq").glob("policy*"))
big = []
little = []
for cpu in sorted(pathlib.Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
    midr = cpu / "regs/identification/midr_el1"
    if midr.exists():
        part = (int(midr.read_text().strip(), 16) >> 4) & 0xfff
        (big if part == 0xd0b else little).append(int(cpu.name[3:]))
if len(big) != 4:
    raise SystemExit("Expected four actual Cortex-A76 cores")
if little:
    os.sched_setaffinity(0, little)  # Keep sampling supervisor on the little cores.
original_governors = {str(p): (p / "scaling_governor").read_text().strip() for p in policies}
expected = {p.name: int((p / "cpuinfo_max_freq").read_text()) for p in policies}
big_policies = [p for p in policies if set(map(int, (p / "affected_cpus").read_text().split())) & set(big)]
temperatures = sorted(pathlib.Path("/sys/class/thermal").glob("thermal_zone*/temp"))
cooling = []
for device in sorted(pathlib.Path("/sys/class/thermal").glob("cooling_device*")):
    if "cpufreq" in (device / "type").read_text().lower():
        cooling.append(device / "cur_state")
sensors = [(p.name+"_cur_khz", p / "scaling_cur_freq") for p in policies]
sensors += [(p.name+"_max_khz", p / "scaling_max_freq") for p in policies]
sensors += [(p.parent.name+"_temp_mc", p) for p in temperatures]
sensors += [(p.parent.name+"_cooling_state", p) for p in cooling]
dmc = pathlib.Path('/sys/class/devfreq/dmc') if args.dmc_performance else None
original_dmc = None
if dmc:
    original_dmc = (dmc/'governor').read_text().strip()
    dmc_available = list(map(int,(dmc/'available_frequencies').read_text().split()))
    dmc_target = max(dmc_available)
    if int((dmc/'max_freq').read_text()) != dmc_target:
        raise SystemExit('DMC max_freq differs from highest available; decision needed before changing caps')
    sensors += [('dmc_cur_hz',dmc/'cur_freq'),('dmc_max_hz',dmc/'max_freq')]
metadata = dict(cooling_note=args.cooling_note, a76_cores=big, supervisor_cores=little,
                expected_max_khz=expected, original_governors=original_governors,
                sampling_interval_s=0.5, status="PREPARING", exit_code=None,
                frequency_drop_detected=False, thermal_cap_detected=False)
metadata.update(feature_mode=args.feature_mode, dmc_controlled=bool(dmc), dmc_frequency_drop=False)
if dmc:
    metadata.update(dmc_original_governor=original_dmc,dmc_available_hz=dmc_available,dmc_target_hz=dmc_target,
                    dmc_original_min_hz=int((dmc/'min_freq').read_text()),dmc_original_max_hz=int((dmc/'max_freq').read_text()))
meta_file = output / "run_metadata.json"


def save():
    temporary = output / 'run_metadata.tmp'
    temporary.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    temporary.replace(meta_file)


def governor(policy, value):
    subprocess.run(["sudo", "-n", "tee", str(policy / "scaling_governor")], input=value+"\n",
                   text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

def dmc_governor(value):
    subprocess.run(['sudo','-n','tee',str(dmc/'governor')],input=value+'\n',text=True,
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)


def sample():
    return {name: int(path.read_text().strip()) for name, path in sensors}


save()
process = None
def interrupted(signum, frame):
    raise RuntimeError('Runner received signal %s; terminating owned SLAM and restoring governors' % signum)
signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
try:
    if not timestamps.is_file():
        raise RuntimeError("Timestamp input does not exist: " + str(timestamps))
    preflight = ["python3", str(ROOT / "scripts/preflight_a2.py")]
    validation = ["python3", str(ROOT / "scripts/validate_prepared.py" if args.dataset_kind=='prepared' else ROOT / "scripts/validate_mh01.py"), str(dataset)]
    if args.settings:
        preflight += ['--output',str(output/'preflight')]
        if args.dataset_kind=='euroc': validation += ['--settings',str(settings),'--output',str(output/'dataset_validation')]
    subprocess.run(preflight, check=True)
    subprocess.run(validation, check=True)
    cooldown_start = time.monotonic()
    while max(int(path.read_text()) for path in temperatures) > 45000:
        if time.monotonic()-cooldown_start > 600:
            raise RuntimeError("Could not cool below 45 C within 10 minutes")
        time.sleep(5)
    metadata["cooldown_seconds"] = time.monotonic()-cooldown_start
    for policy in policies:
        governor(policy, "performance")
        if (policy / "scaling_governor").read_text().strip() != "performance":
            raise RuntimeError("Governor did not become performance")
    if dmc:
        dmc_governor('performance')
    time.sleep(1)
    if dmc:
        metadata['dmc_governor_during']=(dmc/'governor').read_text().strip()
        if metadata['dmc_governor_during']!='performance' or int((dmc/'cur_freq').read_text())!=dmc_target:
            raise RuntimeError('DMC performance did not reach highest available frequency')
    metadata["before_sensors"] = sample()
    metadata["governors_during_run"] = {p.name: (p / "scaling_governor").read_text().strip() for p in policies}
    command = ["taskset", "-c", ",".join(map(str, big)), str(source / "Examples/Monocular/mono_euroc"),
               str(source / "Vocabulary/ORBvoc.txt"), str(settings),
               str(dataset), str(timestamps), args.sequence, "--no-viewer"]
    if args.feature_mode:
        command += ['--feature-mode',args.feature_mode]
    if args.feature_dir:
        command += ['--feature-dir',str(pathlib.Path(args.feature_dir).resolve())]
    metadata["command"] = command
    metadata["settings_sha256"] = hashlib.sha256(settings.read_bytes()).hexdigest()
    metadata.update(dataset_kind=args.dataset_kind,sequence=args.sequence,
                    timestamps_sha256=hashlib.sha256(pathlib.Path(command[7]).read_bytes()).hexdigest())
    (output / "settings.yaml").write_bytes(settings.read_bytes())
    metadata["orb_commit"] = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    metadata["binary_sha256"] = hashlib.sha256((source / "Examples/Monocular/mono_euroc").read_bytes()).hexdigest()
    env = os.environ.copy()
    env.pop("DISPLAY", None)
    env.pop("OPENCV_CORE_PLUGIN_PATH", None)
    env.pop("OPENCV_UI_BACKEND", None)
    env["LD_LIBRARY_PATH"] = str(ROOT / "install/lib") + (":"+env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    start = time.monotonic()
    metadata.update(status="RUNNING", start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save()
    with (output / "program.log").open("wb") as log, (output / "telemetry.csv").open("w", newline="") as data:
        writer = csv.DictWriter(data, fieldnames=["elapsed_s", "utc", "phase"]+[name for name, path in sensors])
        writer.writeheader()
        process = subprocess.Popen(command, cwd=str(output), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        metadata["slam_pid"] = process.pid
        save()
        while True:
            values = sample()
            phase = "tracking_or_shutdown" if (output / "TrackingStates.csv").exists() else "startup"
            writer.writerow(dict(elapsed_s=time.monotonic()-start,
                                 utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), phase=phase, **values))
            data.flush()
            if dmc:
                metadata['dmc_frequency_drop'] |= values['dmc_cur_hz'] < dmc_target or values['dmc_max_hz'] < dmc_target
            if phase == "tracking_or_shutdown":
                for policy in big_policies:
                    metadata["frequency_drop_detected"] |= values[policy.name+"_cur_khz"] < expected[policy.name]
                    metadata["thermal_cap_detected"] |= values[policy.name+"_max_khz"] < expected[policy.name]
                metadata["thermal_cap_detected"] |= any(values[p.parent.name+"_cooling_state"] > 0 for p in cooling)
            code = process.poll()
            if args.stop_on_frequency_drop and code is None and (metadata["frequency_drop_detected"] or metadata["thermal_cap_detected"] or metadata['dmc_frequency_drop']):
                metadata.update(status="THERMAL_PAUSE", error="A76/DMC frequency drop / CPU thermal cap; batch must pause")
                save()
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                metadata.update(exit_code=process.returncode, wall_time_s=time.monotonic()-start)
                break
            if code is None and time.monotonic()-start > 0.5 and "observed_affinity" not in metadata:
                metadata["observed_affinity"] = sorted(os.sched_getaffinity(process.pid))
                if metadata["observed_affinity"] != big:
                    raise RuntimeError("Actual SLAM process affinity differs from A76 set")
            if code is not None:
                metadata.update(exit_code=code, status="FINISHED" if code == 0 else "FAILED",
                                wall_time_s=time.monotonic()-start)
                break
            if time.monotonic()-start > 1800:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise RuntimeError("MH01 exceeded 30-minute per-attempt limit")
            time.sleep(0.5)
    metadata["after_sensors"] = sample()
except Exception as error:
    metadata.update(status="FAILED", error=str(error))
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait()
    if dmc:
        try:
            dmc_governor(original_dmc)
            metadata['dmc_governor_after']=(dmc/'governor').read_text().strip()
            metadata['dmc_restored']=(metadata['dmc_governor_after']==original_dmc and
                int((dmc/'min_freq').read_text())==metadata['dmc_original_min_hz'] and
                int((dmc/'max_freq').read_text())==metadata['dmc_original_max_hz'])
        except Exception as error:
            metadata.update(dmc_restored=False,dmc_restore_error=str(error))
    for policy in policies:
        try:
            governor(policy, original_governors[str(policy)])
        except Exception as error:
            metadata["restore_error_"+policy.name] = str(error)
    metadata["governors_after"] = {p.name:(p / "scaling_governor").read_text().strip() for p in policies}
    metadata["governors_restored"] = all(metadata["governors_after"][p.name] == original_governors[str(p)] for p in policies)
    save()
print("A2_ATTEMPT status=%s exit=%s freq_drop=%s thermal_cap=%s output=%s" %
      (metadata["status"], metadata["exit_code"], metadata["frequency_drop_detected"], metadata["thermal_cap_detected"], output))
if metadata["status"] != "FINISHED" or not metadata['governors_restored'] or (dmc and not metadata.get('dmc_restored',False)):
    raise SystemExit(1)
