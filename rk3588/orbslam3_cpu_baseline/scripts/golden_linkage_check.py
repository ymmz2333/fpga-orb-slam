#!/usr/bin/env python3
"""Validate both independent ELF prefixes before expensive G1 runtime gates."""
import argparse
import hashlib
import json
import pathlib
from run_pc_slam import library_environment, verify_linkage

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = EXPERIMENT.parents[1]


def pc_baseline():
    latest = (EXPERIMENT / 'runtime/pc/latest_job.txt').read_text(encoding='utf-8-sig').strip()
    record = json.loads((EXPERIMENT / 'runtime/pc' / latest / 'environment.json').read_text(encoding='utf-8'))
    paths = [pathlib.Path(p) for p in record['binary_sha256'] if p.endswith('/Examples/Monocular/mono_euroc')]
    if len(paths) != 1:
        raise RuntimeError('PC0 manifest must identify one original native binary')
    binary = paths[0]
    actual = hashlib.sha256(binary.read_bytes()).hexdigest()
    if actual != record['binary_sha256'][str(binary)]:
        raise RuntimeError('Original PC0 binary changed since environment acceptance')
    return binary


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True, type=pathlib.Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    binaries = [pc_baseline(), PROJECT / '.work/golden/slam_source/Examples/Monocular/mono_euroc']
    results = []
    for index, binary in enumerate(binaries):
        environment, library = library_environment(binary)
        text = verify_linkage(binary, environment, library)
        (args.output / ('binary_%d.ldd.txt' % index)).write_text(text)
        results.append(dict(binary=str(binary), library_directory=str(library), status='PASS',
                            sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
        print('LINKAGE_PASS', binary, 'OpenCV4.5.5 build prefix=' + str(library), flush=True)
    (args.output / 'state.json').write_text(json.dumps(dict(status='PASSED', binaries=results), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
