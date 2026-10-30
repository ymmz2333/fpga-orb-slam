#!/usr/bin/env python3
"""HDMI demo evidence only; never set affinity/governors or write experiment CSV."""
import argparse
import csv
import json
import os
import pathlib
import statistics
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--project', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
root, output = pathlib.Path(args.project), pathlib.Path(args.output)
policies = sorted(pathlib.Path('/sys/devices/system/cpu/cpufreq').glob('policy*'))
def governors():
    return {p.name:(p/'scaling_governor').read_text().strip() for p in policies}
before = governors()
source = root / 'vendor/ORB_SLAM3'
command = [str(source/'Examples/Monocular/mono_euroc'), str(source/'Vocabulary/ORBvoc.txt'),
           str(root/'demo/EuRoC_demo.yaml'), str(pathlib.Path.home()/'data/euroc/MH_01_easy'),
           str(source/'Examples/Monocular/EuRoC_TimeStamps/MH01.txt'), 'MH01_DEMO', '--viewer']
result = dict(purpose='DEMO ONLY; excluded from all experimental summaries',
              display=os.environ['DISPLAY'], xauthority=os.environ['XAUTHORITY'],
              command=command, governors_before=before, measured_cpu_percent_definition='100% = one logical core')
(output/'metadata.json').write_text(json.dumps(result, indent=2))
hz = os.sysconf('SC_CLK_TCK')
cores = os.cpu_count()
samples = []
arranged = False
start = time.monotonic()
with (output/'program.log').open('wb') as log, (output/'cpu.csv').open('w', newline='') as stream:
    process = subprocess.Popen(command, cwd=str(output), stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    result['pid'] = process.pid
    result['affinity'] = sorted(os.sched_getaffinity(process.pid))
    (output/'metadata.json').write_text(json.dumps(result, indent=2))
    writer = csv.writer(stream)
    writer.writerow(['elapsed_s','process_cpu_percent','fraction_of_all_cpu_percent','observed_states_rows','phase'])
    previous = None
    while process.poll() is None:
        now = time.monotonic()
        try:
            fields = pathlib.Path('/proc/%d/stat'%process.pid).read_text().rsplit(')',1)[1].split()
            ticks = int(fields[11])+int(fields[12])
        except FileNotFoundError:
            break
        if previous:
            cpu = 100*(ticks-previous[1])/hz/(now-previous[0])
            state = output/'TrackingStates.csv'
            rows = max(0,len(state.read_text().splitlines())-1) if state.exists() else 0
            phase = 'tracking_or_shutdown' if state.exists() else 'startup'
            if state.exists() and not arranged:
                arrangement = subprocess.run(['python3',str(root/'scripts/arrange_demo_windows.py')],
                                             stdout=log,stderr=log)
                arranged = arrangement.returncode == 0
            samples.append(dict(elapsed_s=now-start,cpu_percent=cpu,phase=phase))
            writer.writerow([now-start,cpu,cpu/cores,rows,phase])
            stream.flush()
        previous = now,ticks
        time.sleep(1)
    code = process.wait()
after = governors()
tracking = [s['cpu_percent'] for s in samples if s['phase']=='tracking_or_shutdown']
result.update(exit_code=code,wall_time_s=time.monotonic()-start,governors_after=after,
              governors_unchanged=before==after,cpu_logical_cores=cores,
              tracking_cpu_mean_percent=statistics.mean(tracking) if tracking else None,
              tracking_cpu_median_percent=statistics.median(tracking) if tracking else None)
(output/'metadata.json').write_text(json.dumps(result, indent=2))
print('DEMO_FINISHED exit=%s governors_unchanged=%s cpu_mean_percent=%s output=%s' %
      (code,before==after,result['tracking_cpu_mean_percent'],output), flush=True)
if code or before != after:
    raise SystemExit(code or 1)
