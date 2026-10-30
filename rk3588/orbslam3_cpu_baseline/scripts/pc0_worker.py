#!/usr/bin/env python3
"""Windows coordinator for serial PC0 memory/build; this never starts B3."""
import datetime
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
from windows_awake import WindowsAwake

ROOT = pathlib.Path(__file__).resolve().parent.parent
DISTRO = 'Ubuntu-20.04'
LINUX_ROOT = '/home/slam/orbslam3_cpu_baseline'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-memory', action='store_true', help='Only when the user waives the PC0 memory test; records SKIPPED_BY_USER, never PASS')
    args = parser.parse_args()
    identifier = 'PC0_' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    output = ROOT / 'runtime/pc' / identifier
    output.mkdir(parents=True)
    state = dict(job_id=identifier, status='STARTING', platform='x86 PC / WSL2',
                 started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 formal_b3_started=False, next_gates=['PC1', 'P2', 'P3', 'MH01 board image hash catalogue'])
    power = json.loads((ROOT / 'runtime/pc/power_change.json').read_text(encoding='utf-8-sig'))
    awake = WindowsAwake()

    def save():
        temp = output / 'state.json.tmp'
        temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
        temp.replace(output / 'state.json')
        (ROOT / 'runtime/pc/latest_job.txt').write_text(identifier, encoding='utf-8')

    def wsl(*args):
        return ['wsl', '-d', DISTRO, '-u', 'root', '--', *args]

    def phase(name, command):
        state.update(status='RUNNING', phase=name)
        save()
        with (output / (name + '.log')).open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
            state['child_pid'] = process.pid
            save()
            code = process.wait()
        state[name + '_exit_code'] = code
        save()
        if code:
            raise RuntimeError('%s failed, exit=%d; full log retained' % (name, code))

    def linux_path(path):
        # wsl.exe consumes Windows backslashes; forward slashes survive its argument parser.
        return subprocess.check_output(wsl('wslpath', '-u', pathlib.Path(path).as_posix()), text=True, encoding='utf-8').strip()

    save()
    try:
        state['windows_execution_request'] = awake.acquire()
        save()
        phase('power_mode', ['powercfg', '/setactive', power['selected']])
        bundle = ROOT / 'runtime/pc/orb_b2.bundle'
        with bundle.open('rb') as stream:
            state['orb_bundle_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        state['project_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT), text=True).strip()
        state['orb_b2_commit'] = 'd3e50c03fc194272c70cb482fd807a025cf7a5cf'
        snapshot = output / 'source.tar'
        phase('source_snapshot', ['git', 'archive', '--format=tar', '--output=' + str(snapshot), state['project_commit'],
                                 'scripts', 'configs', 'patches', 'tools', 'docs',
                                 'reports/a2/MH01.txt', 'reports/a2/reference', 'reports/c1/dataset_manifest.json',
                                 'reports/b2/B2_design_smoke_01/raw/candidate_checks',
                                 'reports/b3_precheck/P1_full_20261005/raw/png_hashes.csv'])
        phase('extract_source', wsl('tar', '-xf', linux_path(snapshot), '-C', LINUX_ROOT))
        verified = json.loads(subprocess.check_output(wsl('cat', LINUX_ROOT + '/runtime/pc/datasets/input_verification.json'), text=True, encoding='utf-8'))
        if verified['pc_copy_hash_mismatches'] or verified['tello_board_image_hashes_matched'] != 3957:
            raise RuntimeError('PC input copy verification failed')
        (output / 'input_verification.json').write_text(json.dumps(verified, indent=2, ensure_ascii=False), encoding='utf-8')
        if args.skip_memory:
            state['memory_acceptance'] = dict(status='SKIPPED_BY_USER', hardware_pass_claimed=False,
                reason='User cancelled the PC memory pressure test on 2026-10-05; original incomplete FAILED record retained')
            save()
        else:
            state['linux_memory_output'] = LINUX_ROOT + '/runtime/pc/' + identifier + '/memory'
            phase('memory', wsl('python3', LINUX_ROOT + '/scripts/pc0_memory.py', '--output', state['linux_memory_output']))
        phase('build', wsl('env', 'BUILD_JOBS=2', 'bash', LINUX_ROOT + '/scripts/pc0_build.sh', linux_path(bundle)))
        state.update(status='SUCCEEDED', exit_code=0, phase='PC0_BUILD_COMPLETE' if args.skip_memory else 'PC0_MEMORY_AND_BUILD_COMPLETE',
                     scope='PC0 preparation only; PC1/P2/P3 still required; B3 not started')
    except Exception as error:
        state.update(status='FAILED', exit_code=1, error=str(error))
    finally:
        try:
            for name, path in [('memory_state.json', state.get('linux_memory_output', '') + '/state.json'),
                               ('environment.json', LINUX_ROOT + '/runtime/pc/environment/environment.json')]:
                if not path.startswith('/'):
                    continue
                if name == 'memory_state.json' and not state.get('linux_memory_output'):
                    continue
                result = subprocess.run(wsl('cat', path), capture_output=True, timeout=30)
                if result.returncode == 0:
                    (output / name).write_bytes(result.stdout)
                    if name == 'memory_state.json':
                        state['memory_acceptance'] = {key: json.loads(result.stdout).get(key) for key in
                            ('status', 'exit_code', 'elapsed_s', 'hardware_incidents', 'failure_reasons')}
        finally:
            restore = subprocess.run(['powercfg', '/setactive', power['original']], capture_output=True)
            state['windows_power_restore_exit_code'] = restore.returncode
            try:
                awake.release()
                state['windows_execution_request_released'] = True
            except Exception as error:
                state['windows_execution_request_release_error'] = str(error)
            state['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save()
    print('%s %s phase=%s B3_NOT_STARTED' % (identifier, state['status'], state.get('phase')), flush=True)
    return state['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
