#!/usr/bin/env python3
"""WSL platform record: upstream stressapptest, 30 minutes, 70% MemAvailable."""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    info = pathlib.Path('/proc/meminfo').read_text()
    available = int(re.search(r'^MemAvailable:\s+(\d+)', info, re.M).group(1))
    mib = available * 70 // (100 * 1024)
    if mib < 1024:
        raise RuntimeError('Insufficient WSL MemAvailable for a meaningful platform record')
    command = ['stressapptest', '-M', str(mib), '-s', '1800', '-m', '4', '-W']
    state = dict(platform='x86 PC / WSL2', status='STARTING', command=command,
                 mem_available_before_kib=available, requested_mib=mib, duration_requested_s=1800,
                 started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 scope='WSL platform record; does not repair or certify RK3588',
                 before_meminfo=info)

    def save():
        temp = output / 'state.json.tmp'
        temp.write_text(json.dumps(state, indent=2))
        temp.replace(output / 'state.json')

    save()
    start = time.monotonic()
    with (output / 'stressapptest.log').open('w') as log, (output / 'memory_samples.csv').open('w') as samples:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        state.update(status='RUNNING', pid=process.pid)
        save()
        print('PC0_MEMORY_STARTED pid=%d requested_mib=%d duration_s=1800' % (process.pid, mib), flush=True)
        samples.write('elapsed_s,utc_epoch_s,mem_available_kib,swap_free_kib\n')
        while process.poll() is None:
            text = pathlib.Path('/proc/meminfo').read_text()
            values = [int(re.search(r'^' + key + r':\s+(\d+)', text, re.M).group(1))
                      for key in ('MemAvailable', 'SwapFree')]
            samples.write('%.3f,%.6f,%d,%d\n' % (time.monotonic() - start, time.time(), values[0], values[1]))
            samples.flush()
            time.sleep(1)
    log = (output / 'stressapptest.log').read_text(errors='replace')
    incidents = [int(value) for value in re.findall(r'Found (\d+) hardware incidents', log)]
    elapsed = time.monotonic() - start
    reasons = []
    if process.returncode != 0:
        reasons.append('STRESSAPPTEST_NONZERO_EXIT')
    if 'Status: PASS' not in log or incidents != [0]:
        reasons.append('STRESSAPPTEST_NOT_ZERO_ERROR_PASS')
    if elapsed < 1800:
        reasons.append('INSUFFICIENT_ACTIVE_DURATION: %.3fs < 1800s; check Windows standby events' % elapsed)
    passed = not reasons
    state.update(status='PASS' if passed else 'FAILED', exit_code=process.returncode,
                 elapsed_s=elapsed, hardware_incidents=incidents, failure_reasons=reasons,
                 finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 after_meminfo=pathlib.Path('/proc/meminfo').read_text())
    save()
    print('PC0_MEMORY_%s exit=%s incidents=%s elapsed_s=%.3f' % (state['status'], process.returncode, incidents, elapsed), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
