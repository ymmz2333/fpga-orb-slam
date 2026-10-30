#!/usr/bin/env python3
"""G1-specific runtime gates; never label old PC1/P2/MIN gates as passing."""
import argparse
import csv
import datetime
import importlib.util
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import time

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = EXPERIMENT.parents[1]
GOLDEN = PROJECT / 'orb_frontend_golden'
sys.path.insert(0, str(GOLDEN / 'scripts'))
from common import DATASETS, stamps, image_path, pgm, sha, write_json
from compare import validate_packet, compare_file
import cv2
from golden_linkage_check import pc_baseline


def rows(path):
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--watchdog-only', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    state = dict(status='RUNNING', phase='watchdog_fixture', platform='x86 PC / WSL2',
                 memory='SKIPPED_BY_USER', board_p1='FAILED; no board execution',
                 old_pc1_p2_min_acceptance='NOT_CLAIMED',
                 v0='G1 integer control, not native byte equivalence', checks=[],
                 started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())

    def save():
        temp = out / 'state.tmp'
        write_json(temp, state)
        temp.replace(out / 'state.json')

    def execute(name, command, expected=0):
        state['phase'] = name
        save()
        print('G1_PREFLIGHT', name, flush=True)
        log_path = out / (name + '.log')
        with log_path.open('w') as log:
            if name.endswith('_golden_generation'):
                result = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                          preexec_fn=module.allow_diagnostic_ptrace)
                progress = time.monotonic()
                last = -1
                while result.poll() is None:
                    time.sleep(2)
                    with log_path.open('rb') as reader:
                        reader.seek(max(0, log_path.stat().st_size - 4096))
                        tail = reader.read().decode(errors='replace')
                    matches = re.findall(r'GOLDEN_SEQUENCE_PROGRESS frames=(\d+)', tail)
                    current = int(matches[-1]) if matches else -1
                    if current > last:
                        last, progress = current, time.monotonic()
                    if time.monotonic() - progress >= 120:
                        snapshot = out / (name + '_failure')
                        snapshot.mkdir()
                        capture = module.capture(result.pid, snapshot)
                        write_json(snapshot / 'capture.json', capture)
                        result.terminate()
                        try:
                            result.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            result.kill()
                            result.wait()
                        raise RuntimeError(name + ': no completed G1 frame for 120 s')
                result.wait()
            else:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode != expected:
            raise RuntimeError('%s exit=%s expected=%s; see %s.log' % (name, result.returncode, expected, name))
        return result

    runner = EXPERIMENT / 'scripts/run_pc_slam.py'
    spec = importlib.util.spec_from_file_location('pc_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from b3_decision import cores
    selected, topology = cores()
    (out / 'topology.txt').write_text(topology)
    cpu = ','.join(map(str, selected))

    def run(name, binary, vocab, yaml, dataset, timestamp, mode='native', features=None, expected=0):
        command = [sys.executable, str(runner), '--binary', str(binary), '--vocabulary', str(vocab),
                   '--yaml', str(yaml), '--dataset', str(dataset), '--timestamps', str(timestamp),
                   '--output', str(out / name), '--sequence', name, '--candidate', mode,
                   '--cores', cpu, '--feature-mode', mode]
        if features:
            command += ['--feature-directory', str(features)]
        execute(name, command, expected)
        return json.loads((out / name / 'run_metadata.json').read_text())

    save()
    try:
        # Run the actual supervisor with its unchanged 120 s limit. The fixture
        # flushes three complete rows, starts multiple threads, then deliberately stalls.
        fixture = out / 'stalled_fixture.py'
        fixture.write_text('#!' + sys.executable + '\n' + '''import pathlib,threading,time
for name,header in [('TrackingStates.csv','frame_index,sequence_index,sequence_frame,timestamp_s,state_before,state_after'),('MapStateStats.csv','frame_index,map_id,relocalized'),('FeatureTimeStats.csv','frame_index,timestamp_ns,role,count')]:
    with pathlib.Path(name).open('w') as f:
        f.write(header+'\\n')
        for i in range(3):
            f.write(('%d,0,%d,%d,2,2' % (i,i,i) if name=='TrackingStates.csv' else '%d,0,0,0' % i)+'\\n'); f.flush()
for _ in range(2): threading.Thread(target=lambda:time.sleep(600),daemon=True).start()
time.sleep(600)
''')
        fixture.chmod(0o755)
        fixture_stamps = out / 'fixture_timestamps.txt'
        fixture_stamps.write_text('1000000000\n101000000000\n201000000000\n301000000000\n')
        result = run('watchdog_fixture', fixture, fixture, fixture, out, fixture_stamps, expected=1)
        assert result['status'] == 'FAILED' and result['completed_frames'] == 3
        assert 'NO_FRAME_PROGRESS_120S' in result['failure_reason']
        assert result['stack_capture_ok'] and result['task_status_files'] >= 3
        assert result['snapshot_saved_before_signal_utc']
        assert all(len(rows(out / 'watchdog_fixture' / f)) == 3 for f in
                   ['TrackingStates.csv', 'MapStateStats.csv', 'FeatureTimeStats.csv'])
        assert module.last_frame(out / 'watchdog_fixture/TrackingStates.csv') == 2
        state['checks'].append(dict(name='P3_actual_120s_watchdog', status='PASS',
                                    partial_frames=3, threads=result['task_status_files'],
                                    global_yama=pathlib.Path('/proc/sys/kernel/yama/ptrace_scope').read_text().strip()))
        save()
        if args.watchdog_only:
            state.update(status='PASSED', phase='watchdog_only_complete')
            save()
            return 0

        binary = PROJECT / '.work/golden/slam_source/Examples/Monocular/mono_euroc'
        vocab = PROJECT / '.work/golden/slam_source/Vocabulary/ORBvoc.txt'
        old_binary = pc_baseline()
        assert sha(GOLDEN / 'build/orb_golden_cli') == 'd1df36b5c81ed4ec4d5cbce0b7573473dfdc4d12c2eecf53db05d8b43cf2376a'
        # Verify scratch contains only the authorized log-flush change relative
        # to canonical source; compare normalized text without changing files.
        source = PROJECT / '.work/golden/slam_source'
        canonical = EXPERIMENT / 'vendor/ORB_SLAM3'
        checked = 0
        for folder in ('src', 'include'):
            for path in (canonical / folder).rglob('*'):
                if path.suffix not in ('.cc', '.cpp', '.h', '.hpp'):
                    continue
                relative = path.relative_to(canonical)
                assert path.read_bytes().replace(b'\r\n', b'\n') == (source / relative).read_bytes().replace(b'\r\n', b'\n'), relative
                checked += 1
        mono = source / 'Examples/Monocular/mono_euroc.cc'
        text = mono.read_text()
        additions = ['    // Headers and completed-frame rows must survive a watchdog termination.\n',
                     '    featureFile.flush();\n', '    mapFile.flush();\n', '    stateFile.flush();\n',
                     '            // Flush after t2: logging does not change TrackMonocular or realtime pacing.\n',
                     '            featureFile.flush();\n', '            mapFile.flush();\n', '            stateFile.flush();\n']
        for line in additions:
            assert line in text
            text = text.replace(line, '', 1)
        assert text == (canonical / 'Examples/Monocular/mono_euroc.cc').read_text()
        state['checks'].append(dict(name='SLAM_source_only_0012_logging', status='PASS', files=checked + 1))
        state['binary_sha256'] = sha(binary)
        save()
        # The PC0 diagnostic producer lacks -march=native; that can alter the
        # floating BRIEF rotation's rounding despite identical keypoint fields.
        # Compile this independent Frame-parity oracle with the actual SLAM
        # CPU flags and OpenCV prefix. G1 and the SLAM binaries remain unchanged.
        oracle_build = out / 'frame_parity_oracle'
        prefix = PROJECT / '.work/golden/opencv-install'
        execute('frame_oracle_configure', ['cmake', '-S', str(EXPERIMENT / 'tools/b2_candidates'),
                '-B', str(oracle_build), '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_FLAGS=-march=native -fPIC',
                '-DORB_SOURCE=' + str(source), '-DORB_REFERENCE=' + str(old_binary.parents[4] / 'runtime/b2/original_reference'),
                '-DORB_CANDIDATE_LAPPING_UPPER=1000', '-DOpenCV_DIR=' + str(prefix / 'lib/cmake/opencv4')])
        execute('frame_oracle_build', ['cmake', '--build', str(oracle_build), '--target', 'orb_candidates', '-j', '2'])
        generator = oracle_build / 'orb_candidates'
        state['frame_oracle'] = dict(binary=str(generator), sha256=sha(generator),
                                    cpu_flags='-march=native -fPIC; Release/O3', opencv_prefix=str(prefix),
                                    archive_pc0_producer='Unchanged; not used for strict Frame parity')
        save()
        # Logging-only patch regression; these short checks are never used as
        # the five fresh full-sequence native baselines of the decision round.
        mh = DATASETS[0]
        mh_stamps = out / 'mh01_600.txt'
        mh_stamps.write_text(''.join(str(ns) + '\n' for ns in stamps(mh)[:600]))
        mh_yaml = EXPERIMENT / 'configs/a3/baseline_752x480.yaml'
        old_vocab = old_binary.parents[2] / 'Vocabulary/ORBvoc.txt'
        old = run('MH01_native_unflushed600', old_binary, old_vocab, mh_yaml, mh['path'], mh_stamps)
        assert old['status'] == 'FINISHED'
        baseline_rows = rows(out / 'MH01_native_unflushed600/TrackingStates.csv')
        old_init = next((i for i, r in enumerate(baseline_rows) if int(r['state_after']) == 2), None)
        assert old_init is not None
        for repeat in range(1, 4):
            name = 'MH01_native_flushed600_%02d' % repeat
            result = run(name, binary, vocab, mh_yaml, mh['path'], mh_stamps)
            assert result['status'] == 'FINISHED'
            current_rows = rows(out / name / 'TrackingStates.csv')
            first = next((i for i, r in enumerate(current_rows) if int(r['state_after']) == 2), None)
            assert first == old_init, 'Logging regression initialization differs; stop for diagnosis'
            assert all(int(r['state_after']) == 2 for r in current_rows[first:]), 'Logging regression lost tracking'
        state['checks'].append(dict(name='P3_MH01_native_logging_regression', status='PASS',
                                    frames=600, patched_repetitions=3, reference_repetitions=1,
                                    initialization_frame=old_init + 1))
        save()
        cv2.setNumThreads(1)
        for d in DATASETS:
            short = out / d['name']
            short.mkdir()
            ns_list = stamps(d)[:150]
            timestamp = short / 'timestamps_150.txt'
            timestamp.write_text(''.join(str(ns) + '\n' for ns in ns_list))
            original = (EXPERIMENT / ('configs/a3/baseline_752x480.yaml' if d['name'] == 'MH01'
                                     else 'configs/c/tello_oafd_960x720_provisional.yaml')).read_text()
            yaml = short / 'native.yaml'
            yaml.write_text(original)
            if d['name'] != 'MH01':
                native_packets = short / 'native_packets'
                dump = run(d['name'] + '_native_dump150', binary, vocab, yaml, d['path'], timestamp, 'dump', native_packets)
                standalone = short / 'standalone_corrected'
                execute(d['name'] + '_standalone', [str(generator), '--config', str(yaml), '--dataset', str(d['path']),
                        '--timestamps', str(timestamp), '--output', str(standalone), '--stride', '1'])
                for ns in ns_list:
                    for role in ('normal', 'initialization'):
                        actual = native_packets / role / (str(ns) + '.orb')
                        result = compare_file(actual, standalone / role / (str(ns) + '.orb'))
                        if not result['equal']:
                            write_json(short / 'first_difference.json', dict(timestamp_ns=ns, role=role, **result))
                            raise ValueError('Actual Frame / independent corrected extractor mismatch')
                        assert actual.read_bytes()[64:] == (native_packets / 'memory' / role / (str(ns) + '.bin')).read_bytes()
                replay = run(d['name'] + '_native_replay150', binary, vocab, yaml, d['path'], timestamp, 'inject', native_packets)
                for name, metadata in [('native_dump150', dump), ('native_replay150', replay)]:
                    assert metadata['status'] == 'FINISHED'
                    records = rows(out / (d['name'] + '_' + name) / 'FeatureTimeStats.csv')
                    assert len(records) == 150
                    for index, row in enumerate(records):
                        ns, role = int(row['timestamp_ns']), int(row['role'])
                        assert ns == ns_list[index] and role in (0, 1)
                        packet = native_packets / ('initialization' if role else 'normal') / (str(ns) + '.orb')
                        assert int(row['count']) == validate_packet(packet.read_bytes())
                        assert int(row['extractor_calls']) == (2 if name == 'native_dump150' else 0)
                left = rows(out / (d['name'] + '_native_dump150') / 'FeatureTimeStats.csv')
                right = rows(out / (d['name'] + '_native_replay150') / 'FeatureTimeStats.csv')
                assert [(r['timestamp_ns'], r['role']) for r in left] == [(r['timestamp_ns'], r['role']) for r in right], 'Native replay role sequence differs; stop for diagnosis'
                state['checks'].append(dict(name='P2_actual_Frame_all150_both_roles', dataset=d['name'],
                                            status='PASS', packets=300, ordered_fields_and_descriptors='byte exact'))
                save()
            # All five G1 candidates and both roles, every timestamp in first150.
            inputs = short / 'pgm'
            inputs.mkdir()
            image_manifest = []
            for index, ns in enumerate(ns_list):
                path = image_path(d, index)
                im = cv2.imread(str(path), 0)
                assert im is not None
                pgm(inputs / (str(ns) + '.pgm'), im)
                image_manifest.append(dict(timestamp_ns=ns, source_sha256=sha(path), pgm_sha256=sha(inputs / (str(ns) + '.pgm'))))
            write_json(short / 'input_hashes.json', image_manifest)
            corpus = short / 'g1'
            execute(d['name'] + '_golden_generation', [str(GOLDEN / 'build/orb_golden_cli'), '--input', str(inputs),
                    '--sequence', str(timestamp), '--output', str(corpus)])
            for variant in ('V0', 'L8', 'L4', 'L2', 'L1'):
                levels = 8 if variant == 'V0' else int(variant[1:])
                for ns in ns_list:
                    for role, role_name in [(0, 'normal'), (1, 'initialization')]:
                        b = (corpus / variant / role_name / (str(ns) + '.orb')).read_bytes()
                        validate_packet(b)
                        assert b[14] == role and struct.unpack_from('<Q', b, 16)[0] == ns
                        assert struct.unpack_from('<I', b, 36)[0] == levels
                        assert struct.unpack_from('<I', b, 44)[0] == (5000 if role else 1000)
                        assert b[40:44] == struct.pack('<f', 1.2)
                variant_yaml = short / (variant + '.yaml')
                variant_yaml.write_text(re.sub(r'(?m)^(ORBextractor.nLevels:)\s*[^\n]+', r'\g<1> ' + str(levels), original))
                metadata = run(d['name'] + '_' + variant + '_inject150', binary, vocab, variant_yaml, d['path'], timestamp, 'inject', corpus / variant)
                assert metadata['status'] == 'FINISHED'
                records = rows(out / (d['name'] + '_' + variant + '_inject150') / 'FeatureTimeStats.csv')
                assert len(records) == 150
                for index, row in enumerate(records):
                    ns, role = int(row['timestamp_ns']), int(row['role'])
                    assert ns == ns_list[index] and role in (0, 1) and int(row['extractor_calls']) == 0
                    packet = corpus / variant / ('initialization' if role else 'normal') / (str(ns) + '.orb')
                    assert int(row['count']) == validate_packet(packet.read_bytes())
                # Initialization quality is a B3 outcome, not a reason to replace a candidate.
                tracking = rows(out / (d['name'] + '_' + variant + '_inject150') / 'TrackingStates.csv')
                state['checks'].append(dict(name='G1_actual_B1_binding', dataset=d['name'], variant=variant,
                                            status='PASS', completed_frames=150, initialization_seen=any(int(r['state_after']) == 2 for r in tracking)))
                save()
        assert sha(binary) == state['binary_sha256']
        state.update(status='PASSED', phase='G1_runtime_gates_complete',
                     scope='New G1 layer round only; old PC1, native/V0 equivalence and MIN tests not claimed')
        save()
        return 0
    except Exception as error:
        state.update(status='FAILED', error=str(error))
        save()
        raise
    finally:
        state['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    raise SystemExit(main())
