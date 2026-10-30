#!/usr/bin/env python3
"""Sequential WSL SLAM runner; 120s completed-frame watchdog and saved hang state."""
import argparse
import csv
import contextlib
import ctypes
import datetime
import fcntl
import json
import os
import pathlib
import re
import signal
import subprocess
import time
from golden_audit_support import canonical_timestamps


def allow_diagnostic_ptrace():
    """Permit same-UID gdb helpers for this child only, without changing Yama globally."""
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_PTRACER / PR_SET_PTRACER_ANY survives exec (taskset -> mono_euroc).
    if libc.prctl(0x59616d61, ctypes.c_ulong(-1), 0, 0, 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def library_environment(binary):
    """Keep each independent build's OpenCV/Pangolin transitives in its own prefix."""
    binary = pathlib.Path(binary).resolve()
    environment = dict(os.environ)
    with binary.open('rb') as stream:
        if stream.read(2) == b'#!':
            return environment, None  # Controlled watchdog executable, not the SLAM ELF.
    candidates = [binary.parents[3] / 'opencv-install/lib', binary.parents[4] / 'install/lib']
    available = [p.resolve() for p in candidates if (p / 'libopencv_core.so.405').exists()]
    if len(available) != 1:
        raise RuntimeError('Cannot identify a unique build-specific library prefix for ' + str(binary))
    library = available[0]
    # DT_RUNPATH does not cover indirect dependencies such as pango_windowing.
    # Do not inherit another build's LD_LIBRARY_PATH into this run.
    environment['LD_LIBRARY_PATH'] = str(library)
    return environment, library


def verify_linkage(binary, environment, library):
    if library is None:
        return 'Controlled script fixture; ELF linkage does not apply\n'
    result = subprocess.run(['ldd', str(binary)], env=environment, capture_output=True, text=True)
    text = result.stdout + result.stderr
    if result.returncode or 'not found' in text:
        raise RuntimeError('Unresolved ELF dependency before launching SLAM: ' + text.strip())
    opencv = re.findall(r'libopencv_\S+\s+=>\s+(\S+)', text)
    if not opencv or any(not pathlib.Path(p).resolve().is_relative_to(library) for p in opencv):
        raise RuntimeError('OpenCV libraries do not belong to the selected build prefix')
    if re.search(r'libopencv_\S*\.4\.2', text):
        raise RuntimeError('OpenCV 4.2 mixed linkage is forbidden')
    version = library / 'cmake/opencv4/OpenCVConfig-version.cmake'
    if not re.search(r'4\.5\.5(?:\D|$)', version.read_text()):
        raise RuntimeError('Expected OpenCV 4.5.5 configuration')
    return text


def last_frame(path):
    if not path.exists():
        return -1
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        text = stream.read().decode('utf-8', errors='replace')
    # A completed CSV row ends with a newline; partial writes never count as progress.
    rows = text.split('\n')[:-1]
    values = [int(line.split(',')[0]) for line in rows if re.match(r'^\d+,\d+,\d+,', line)]
    return max(values, default=-1)


def capture(pid, output):
    target = output / 'hang_snapshot'
    target.mkdir()
    proc = pathlib.Path('/proc') / str(pid)
    for task in sorted((proc / 'task').glob('*')):
        for name in ('wchan', 'status'):
            try:
                (target / (task.name + '_' + name + '.txt')).write_bytes((task / name).read_bytes())
            except OSError as error:
                (target / (task.name + '_' + name + '.error.txt')).write_text(str(error))
    args = ['gdb', '-q', '-batch', '-p', str(pid), '-ex', 'set pagination off',
            '-ex', 'thread apply all bt', '-ex', 'detach']
    with (target / 'threads.gdb.txt').open('w') as log:
        try:
            result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=30)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 'TIMEOUT'
    text = (target / 'threads.gdb.txt').read_text(errors='replace')
    passed = code == 0 and '#0' in text and bool(re.search(r'Thread\s+\d+', text)) and 'ptrace: Operation not permitted' not in text
    return dict(gdb_exit=code, stack_capture_ok=passed, task_status_files=len(list(target.glob('*_status.txt'))))


def cleanup_monitor_error(process, state, save, error):
    if error is None:
        return False
    state.update(status='FAILED', failure_reason='SUPERVISOR_ERROR: ' + str(error))
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            process.wait()
    state.update(exit_code=process.returncode, end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save()
    return False  # Preserve the supervisor traceback; never promote it to a candidate failure.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'vocabulary', 'yaml', 'dataset', 'timestamps', 'output', 'sequence', 'candidate'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--feature-mode', choices=('native', 'dump', 'inject'), default='native')
    parser.add_argument('--feature-directory')
    parser.add_argument('--cores', required=True, help='Four distinct WSL CPU/CORE representatives')
    parser.add_argument('--duration-factor', type=float, default=6)
    parser.add_argument('--wait-lock', action='store_true', help='Acquire the exclusive SLAM lock in this runner without an outer probe race')
    args = parser.parse_args()
    if args.duration_factor < 1:
        raise ValueError('Realtime duration cap factor must be >= 1')
    selected = [int(value) for value in args.cores.split(',')]
    if len(selected) != 4 or len(set(selected)) != 4:
        raise ValueError('Exactly four distinct logical CPU IDs required')
    topology = subprocess.check_output(['lscpu', '-p=CPU,CORE,SOCKET'], universal_newlines=True)
    groups = {int(parts[0]): tuple(parts[1:]) for parts in (line.split(',') for line in topology.splitlines() if not line.startswith('#'))}
    if len({groups[cpu] for cpu in selected}) != 4:
        raise ValueError('Selected CPUs include SMT siblings')
    lock = open('/tmp/orb_b3_pc_slam.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | (0 if args.wait_lock else fcntl.LOCK_NB))
    stamps = [int(line) for line in pathlib.Path(args.timestamps).read_text().splitlines() if line.strip()]
    if not stamps or any(a >= b for a, b in zip(stamps, stamps[1:])):
        raise ValueError('Timestamp sequence must be strictly increasing integer nanoseconds')
    duration = (stamps[-1] - stamps[0]) * 1e-9
    total_cap = 120 + args.duration_factor * duration
    output = pathlib.Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = ['taskset', '-c', args.cores, str(pathlib.Path(args.binary).resolve()),
               str(pathlib.Path(args.vocabulary).resolve()), str(pathlib.Path(args.yaml).resolve()),
               str(pathlib.Path(args.dataset).resolve()), str(pathlib.Path(args.timestamps).resolve()),
               args.sequence, '--no-viewer', '--feature-mode', args.feature_mode]
    if args.feature_mode != 'native':
        if not args.feature_directory:
            raise ValueError('Feature directory is required for dump/inject')
        command += ['--feature-dir', str(pathlib.Path(args.feature_directory).resolve())]
    state = dict(platform='x86 PC / WSL2', sequence=args.sequence, candidate=args.candidate,
                 status='STARTING', command=command, expected_frames=len(stamps),
                 watchdog_s=120, realtime_duration_s=duration, total_cap_s=total_cap,
                 timing_scope='watchdog and health only; not performance or FPGA evidence',
                 start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())

    def save():
        temp = output / 'run_metadata.json.tmp'
        temp.write_text(json.dumps(state, indent=2))
        temp.replace(output / 'run_metadata.json')

    save()
    _,canonical=canonical_timestamps(args.timestamps)
    if pathlib.Path(args.timestamps).read_bytes()!=canonical:
        state.update(status='FAILED',failure_reason='INPUT_TIMESTAMP_FORMAT: require ASCII integer nanoseconds, LF only, one value per line',completed_frames=0,exit_code=None)
        save()
        lock.close()
        return 1
    try:
        environment, library = library_environment(pathlib.Path(args.binary))
        linked = verify_linkage(pathlib.Path(args.binary), environment, library)
        (output / 'linkage.ldd.txt').write_text(linked)
    except Exception as error:
        state.update(status='FAILED', failure_reason='ELF_LINKAGE_CHECK: ' + str(error), exit_code=None)
        save()
        print('PC_RUN linkage validation failed before spawn: ' + str(error))
        lock.close()
        return 1
    state['library_directory'] = str(library) if library else None
    state['linkage_verified_before_spawn'] = True
    save()
    start = progress_at = time.monotonic()
    completed = -1
    with (output / 'run.log').open('w') as log, contextlib.ExitStack() as guard:
        try:
            process = subprocess.Popen(command, cwd=str(output), stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, preexec_fn=allow_diagnostic_ptrace, env=environment)
        except Exception as error:
            state.update(status='FAILED', failure_reason='PROCESS_SPAWN: ' + str(error), exit_code=None,
                         completed_frames=0, end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            save()
            lock.close()
            return 1
        state.update(status='RUNNING', slam_pid=process.pid,
                     diagnostic_ptrace='child-scoped PR_SET_PTRACER_ANY; global Yama unchanged')
        guard.push(lambda kind, error, traceback: cleanup_monitor_error(process, state, save, error))
        save()
        while process.poll() is None:
            current = last_frame(output / 'TrackingStates.csv')
            now = time.monotonic()
            if current > completed:
                completed = current
                progress_at = now
                state['completed_frames'] = completed + 1
                try:
                    state['observed_affinity'] = sorted(os.sched_getaffinity(process.pid))
                except ProcessLookupError:
                    pass  # The child may exit between poll() and the affinity read.
                save()
            reason = 'NO_FRAME_PROGRESS_120S' if now - progress_at >= 120 else ('TOTAL_DURATION_CAP' if now - start >= total_cap else None)
            if reason:
                state.update(status='CAPTURING_HANG', failure_reason='%s/%s: %s' % (args.sequence, args.candidate, reason))
                save()
                try:
                    state.update(capture(process.pid, output))
                except Exception as error:
                    # A diagnostic failure blocks acceptance but must not leave SLAM alive.
                    state.update(stack_capture_ok=False, capture_error=str(error))
                state['snapshot_saved_before_signal_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                save()
                # Capture precedes every termination signal.
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGINT)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
            time.sleep(1)
    completed = last_frame(output / 'TrackingStates.csv') + 1
    state.update(status='FINISHED' if process.returncode == 0 and completed == len(stamps) and 'failure_reason' not in state else 'FAILED',
                 exit_code=process.returncode, completed_frames=completed, wall_time_s=time.monotonic() - start,
                 end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save()
    print('PC_RUN %s %s %s frames=%d/%d exit=%s' % (args.sequence, args.candidate, state['status'], completed, len(stamps), process.returncode))
    lock.close()
    return 0 if state['status'] == 'FINISHED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
