#!/usr/bin/env python3
"""Isolate a native/standalone BRIEF discrepancy without changing SLAM or G1."""
import argparse
import csv
import hashlib
import json
import pathlib
import subprocess
import sys
from golden_linkage_check import pc_baseline
from run_pc_slam import library_environment

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = EXPERIMENT.parents[1]
GOLDEN = PROJECT / 'orb_frontend_golden'
sys.path.insert(0, str(GOLDEN / 'scripts'))
from compare import compare_file


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--failed-batch', required=True)
    p.add_argument('--output', required=True, type=pathlib.Path)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    ds_name = 'flight_20261004T184929_998838_6bb93c56'
    failed = GOLDEN / 'decision' / (a.failed_batch + '_preflight') / ds_name
    first = json.loads((failed / 'first_difference.json').read_text())
    ns = first['timestamp_ns']
    timestamp = out / 'one_timestamp.txt'
    timestamp.write_text(str(ns) + '\n')
    dataset = EXPERIMENT / 'runtime/c/datasets/TT_C1_01' / ds_name
    config = failed / 'native.yaml'
    native = failed / 'native_packets/initialization' / (str(ns) + '.orb')
    baseline = pc_baseline()
    pc_root = baseline.parents[4]
    source = PROJECT / '.work/golden/slam_source'
    reference = pc_root / 'runtime/b2/original_reference'
    results = []

    def run(name, args, env=None):
        with (out / (name + '.log')).open('w') as log:
            subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, env=env, check=True)

    def extract(label, executable, prefix, repeat=0):
        folder = out / ('packets_' + label + '_%d' % repeat)
        env = dict(library_environment(source / 'Examples/Monocular/mono_euroc')[0])
        env['LD_LIBRARY_PATH'] = str(prefix / 'lib')
        run(label + '_extract_%d' % repeat, [str(executable), '--config', str(config), '--dataset', str(dataset),
            '--timestamps', str(timestamp), '--output', str(folder), '--stride', '1'], env)
        packet = folder / 'initialization' / (str(ns) + '.orb')
        expected, actual = native.read_bytes(), packet.read_bytes()
        row = dict(profile=label, repeat=repeat, prefix=str(prefix), equal=expected == actual,
                   sha256=hashlib.sha256(actual).hexdigest(), native_sha256=hashlib.sha256(expected).hexdigest(),
                   bit_differences=sum((x ^ y).bit_count() for x, y in zip(expected, actual)),
                   first_difference=compare_file(native, packet))
        results.append(row)
        print('DESCRIPTOR_DIAGNOSTIC', label, repeat, 'equal=' + str(row['equal']), 'bits=' + str(row['bit_differences']), flush=True)

    # Repeat the original mismatching producer to distinguish stable numeric
    # differences from sporadic in-memory corruption.
    for i in range(3):
        extract('default_old_cv', pc_root / 'build/b2_candidates_corrected/orb_candidates', pc_root / 'install', i)
    for label, flags, prefix in [
            ('default_new_cv', '-fPIC', PROJECT / '.work/golden/opencv-install'),
            ('native_old_cv', '-march=native -fPIC', pc_root / 'install'),
            ('native_new_cv', '-march=native -fPIC', PROJECT / '.work/golden/opencv-install')]:
        build = out / ('build_' + label)
        run(label + '_configure', ['cmake', '-S', str(EXPERIMENT / 'tools/b2_candidates'), '-B', str(build),
            '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_FLAGS=' + flags, '-DORB_SOURCE=' + str(source),
            '-DORB_REFERENCE=' + str(reference), '-DORB_CANDIDATE_LAPPING_UPPER=1000',
            '-DOpenCV_DIR=' + str(prefix / 'lib/cmake/opencv4')])
        run(label + '_build', ['cmake', '--build', str(build), '--target', 'orb_candidates', '-j', '2'])
        extract(label, build / 'orb_candidates', prefix)
    # Same real SLAM extractor, same single image, alternate extraction order:
    # protects against treating a one-off archived in-memory bit flip as FMA.
    for i in range(3):
        folder = out / ('native_dump_%d' % i)
        features = out / ('native_features_%d' % i)
        run('native_dump_%d' % i, [sys.executable, str(EXPERIMENT / 'scripts/run_pc_slam.py'),
            '--binary', str(source / 'Examples/Monocular/mono_euroc'), '--vocabulary', str(source / 'Vocabulary/ORBvoc.txt'),
            '--yaml', str(config), '--dataset', str(dataset), '--timestamps', str(timestamp), '--output', str(folder),
            '--sequence', 'descriptor_diagnostic', '--candidate', 'native_dump', '--cores', '0,2,4,6',
            '--feature-mode', 'dump', '--feature-directory', str(features)])
        packet = features / 'initialization' / (str(ns) + '.orb')
        results.append(dict(profile='actual_Frame_repeat', repeat=i, equal=native.read_bytes() == packet.read_bytes(),
                            sha256=hashlib.sha256(packet.read_bytes()).hexdigest(), first_difference=compare_file(native, packet)))
    (out / 'diagnosis.json').write_text(json.dumps(dict(failed_batch=a.failed_batch, timestamp_ns=ns,
        source='unchanged ORBextractor; only independent oracle compile flags and OpenCV prefix varied', rows=results), indent=2))
    print('DESCRIPTOR_DIAGNOSIS_COMPLETE', out, flush=True)


if __name__ == '__main__':
    main()
