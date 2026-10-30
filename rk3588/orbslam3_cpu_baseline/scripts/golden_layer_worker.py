#!/usr/bin/env python3
"""Windows awake/power coordinator: G1 gates, existing 90-slot launcher, then stop."""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
from windows_awake import WindowsAwake

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = EXPERIMENT.parents[1]
GOLDEN = PROJECT / 'orb_frontend_golden'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--acceptance', required=True, type=pathlib.Path)
    parser.add_argument('--verify-only', action='store_true', help='Exercise the entire Windows/WSL launch gate without launching a batch')
    parser.add_argument('--resume-from', type=pathlib.Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.batch):
        raise ValueError('Unsafe batch name')
    output = GOLDEN / 'decision' / (args.batch + '_coordinator')
    output.mkdir(exist_ok=False)
    if (GOLDEN / 'decision' / args.batch).exists():
        raise ValueError('Do not relaunch an existing batch')
    power = json.loads((EXPERIMENT / 'runtime/pc/power_change.json').read_text(encoding='utf-8-sig'))
    active_power = subprocess.check_output(['powercfg', '/getactivescheme'], text=True, encoding='utf-8', errors='replace')
    previous_power = re.search(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', active_power).group(0)
    awake = WindowsAwake()
    state = dict(status='STARTING', phase='preparing', batch=args.batch, formal_b3_started=False,
                 started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 platform='x86 PC / WSL2', memory='SKIPPED_BY_USER', board='NO_EXECUTION')

    def save():
        temporary = output / 'state.tmp'
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(output / 'state.json')

    def command(*arguments):
        return ['wsl', '-d', 'Ubuntu-20.04', '-u', 'root', '--', *arguments]

    def linux(path):
        return subprocess.check_output(command('wslpath', '-u', pathlib.Path(path).as_posix()),
                                       text=True, encoding='utf-8').strip()

    def phase(name, cmd):
        state.update(status='RUNNING', phase=name)
        save()
        with (output / (name + '.log')).open('wb') as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            state['child_pid'] = child.pid
            save()
            result = child.wait()
        state[name + '_exit_code'] = result
        save()
        if result:
            raise RuntimeError('%s failed, exit=%d; preserved log' % (name, result))

    save()
    try:
        frozen_paths = [GOLDEN / name for name in ('golden.cpp', 'golden.hpp', 'constants.hpp', 'main.cpp',
                       'DESIGN_SPEC_v0.9.md', 'FORMAT.md', 'delivery/DELIVERY_REPORT.md', 'build/orb_golden_cli')]
        frozen_paths += list((GOLDEN / 'scripts').glob('*.py')) + [GOLDEN / 'scripts/build_slam.sh']
        frozen_paths += [EXPERIMENT / 'scripts' / name for name in ('run_pc_slam.py', 'golden_layer_preflight.py',
                        'golden_layer_worker.py', 'golden_linkage_check.py', 'windows_awake.py', 'analyze_c.py', 'analyze_a2.py', 'evaluate_a2.py', 'finish_c.py')]
        frozen_paths += [EXPERIMENT / 'scripts' / name for name in ('golden_decision_audited.py','golden_report_audited.py','golden_decision_launch.py','golden_audit_support.py','golden_resume_audit.py','golden_runtime_check.py','golden_decision_resume.py')]
        if args.resume_from:frozen_paths += [args.resume_from/'batch_state.json']
        frozen_paths += [args.acceptance]
        hashes = {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_paths}
        state['source_sha256'] = hashes
        state['git_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=EXPERIMENT, text=True).strip()
        state['previous_power_scheme'] = previous_power
        state['windows_execution_request'] = awake.acquire()
        save()
        phase('power', ['powercfg', '/setactive', power['selected']])
        root = linux(GOLDEN)
        python = root + '/.venv-wsl/bin/python'
        # Authoritative scripts/configs remain under D:\pld. Freeze their hashes
        # and preserve independent scratch builds; never modify vendor code.
        # Build and runtime gates were completed before this unattended launch.
        # Do not rebuild an accepted executable inside the formal batch.
        phase('verify_linkage', command(python, linux(EXPERIMENT / 'scripts/golden_linkage_check.py'),
                                       '--output', linux(GOLDEN / 'decision' / (args.batch + '_linkage'))))
        acceptance = json.loads(args.acceptance.read_text(encoding='utf-8'))
        if acceptance['status'] != 'PASSED':
            raise RuntimeError('G1 runtime gates are not PASSED')
        if hashlib.sha256((PROJECT / '.work/golden/slam_source/Examples/Monocular/mono_euroc').read_bytes()).hexdigest() != acceptance['binary_sha256']:
            raise RuntimeError('Accepted SLAM binary changed after audit')
        # Linux symlinks under /mnt/d are not readable as native Windows files.
        # Every Linux artifact (including /lib transitives) is checked by Linux.
        phase('verify_accepted_runtime', command(python,linux(EXPERIMENT/'scripts/golden_runtime_check.py'),'--acceptance',linux(args.acceptance)))
        for relative, digest in hashes.items():
            if hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Frozen source changed: ' + relative)
        state.update(preflight_status=acceptance['status'], phase='launch_decision')
        save()
        if args.verify_only:
            state.update(status='VERIFIED_ONLY',phase='all_launch_gates_verified_no_batch',formal_b3_started=False)
            save()
            return 0
        launch=command(python, linux(EXPERIMENT / 'scripts/golden_decision_launch.py'), '--batch', args.batch,'--acceptance',linux(args.acceptance))
        if args.resume_from:launch+=['--resume-from',linux(args.resume_from)]
        receipt = subprocess.check_output(launch,
                                          text=True, encoding='utf-8')
        (output / 'launch_receipt.json').write_text(receipt, encoding='utf-8')
        launched = json.loads(receipt)
        state.update(decision_pid=launched['pid'], phase='decision_pipeline',
                     formal_b3_started=False, pipeline_launched=True)
        save()
        # This is the unattended coordinator, not agent log polling. Keep its
        # Windows execution request alive, restore power only on final state.
        final = GOLDEN / 'decision' / args.batch / 'batch_state.json'
        while True:
            time.sleep(15)
            if not final.exists():
                alive = subprocess.run(command('kill', '-0', str(launched['pid'])), capture_output=True).returncode == 0
                if not alive:
                    raise RuntimeError('Decision child exited without a final state')
                continue
            try:
                result = json.loads(final.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                continue
            state.update(decision_phase=result['phase'], completed=result['completed'],
                         formal_b3_started=result['completed'] > 0 or result['phase'] == 'decision_runs')
            save()
            if result['status'] == 'FINISHED_AWAIT_LAYER_DECISION':
                state.update(status='FINISHED_AWAIT_LAYER_DECISION', phase='await_user_layer_choice',
                             report=str(final.parent / 'report/REPORT.md'))
                break
            if result['status'] == 'FAILED':
                raise RuntimeError('Decision pipeline failed: ' + result.get('error', 'see batch state'))
            alive = subprocess.run(command('kill', '-0', str(launched['pid'])), capture_output=True).returncode == 0
            if not alive:
                raise RuntimeError('Decision child lost without trustworthy completion')
    except Exception as error:
        state.update(status='FAILED', error=str(error))
    finally:
        state['power_restore_exit_code'] = subprocess.run(['powercfg', '/setactive', previous_power], capture_output=True).returncode
        awake.release()
        state['awake_released'] = True
        state['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    return 0 if state['status'] in ('FINISHED_AWAIT_LAYER_DECISION','VERIFIED_ONLY') else 1


if __name__ == '__main__':
    raise SystemExit(main())
