#!/usr/bin/env python3
"""Record the actual WSL build, versions, linking and binary hashes; no timings."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(argv):
    return subprocess.check_output(argv, stderr=subprocess.STDOUT, universal_newlines=True).strip()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'vendor/ORB_SLAM3'
    binaries = [source / 'Examples/Monocular/mono_euroc', source / 'lib/libORB_SLAM3.so',
                source / 'Thirdparty/DBoW2/lib/libDBoW2.so', source / 'Thirdparty/g2o/lib/libg2o.so']
    binaries += [ROOT / ('build/b2_candidates_' + name + '/orb_candidates') for name in ('corrected', 'legacy')]
    links = {}
    for path in binaries:
        text = run(['ldd', str(path)])
        (output / (path.name + '_' + path.parent.name + '.ldd.txt')).write_text(text + '\n')
        if 'not found' in text or re.search(r'opencv[^\n]*4\.2', text):
            raise RuntimeError('Missing/mixed dependency: ' + str(path))
        for library in re.findall(r'=>\s+(/\S+)', text):
            p = pathlib.Path(library).resolve()
            links[str(p)] = sha(p)
            if 'libopencv' in p.name and not p.name.endswith('.4.5.5'):
                raise RuntimeError('Unexpected OpenCV version: ' + str(p))
    for path in binaries:
        links[str(path)] = sha(path)
    topology = []
    for line in run(['lscpu', '-p=CPU,CORE,SOCKET']).splitlines():
        if line.startswith('#'):
            continue
        cpu, core, socket = map(int, line.split(','))
        topology.append(dict(cpu=cpu, core=core, socket=socket))
    groups = {}
    for row in topology:
        if row['cpu'] in os.sched_getaffinity(0):
            groups.setdefault((row['socket'], row['core']), []).append(row['cpu'])
    affinity = [min(cpus) for cpus in groups.values()][:4]
    if len(affinity) != 4:
        raise RuntimeError('Cannot select four distinct WSL-reported cores')
    caches = {}
    for name, path in [('opencv', ROOT / 'build/opencv'), ('Pangolin', ROOT / 'build/Pangolin'),
                       ('ORB_SLAM3', source / 'build')]:
        text = (path / 'CMakeCache.txt').read_text()
        fields = dict(re.findall(r'(?m)^(CMAKE_(?:BUILD_TYPE|CXX_FLAGS|CXX_FLAGS_RELEASE|CXX_COMPILER)):[^=]*=(.*)$', text))
        if fields.get('CMAKE_BUILD_TYPE') != 'Release' or '-O3' not in fields.get('CMAKE_CXX_FLAGS_RELEASE', ''):
            raise RuntimeError('Expected Release/O3: ' + name)
        caches[name] = fields
    result = dict(platform='x86 PC / WSL2', timing_scope='watchdog/health only; no performance or FPGA conclusions',
                  cpu=run(['lscpu']), kernel=run(['uname', '-r']), os=pathlib.Path('/etc/os-release').read_text(),
                  memory=pathlib.Path('/proc/meminfo').read_text(), gcc=run(['gcc', '--version']).splitlines()[0],
                  cmake=run(['cmake', '--version']).splitlines()[0],
                  packages=run(['dpkg-query', '-W', '-f=${Package},${Version}\n', 'gcc-9', 'g++-9', 'libeigen3-dev',
                                'libboost-serialization-dev', 'stressapptest']),
                  orb_commit=run(['git', '-C', str(source), 'rev-parse', 'HEAD']),
                  orb_tree=run(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}']),
                  opencv_commit=run(['git', '-C', str(ROOT / 'vendor/opencv'), 'rev-parse', 'HEAD']),
                  opencv_tag=run(['git', '-C', str(ROOT / 'vendor/opencv'), 'describe', '--tags', '--exact-match']),
                  pangolin_commit=run(['git', '-C', str(ROOT / 'vendor/Pangolin'), 'rev-parse', 'HEAD']),
                  pangolin_tag=run(['git', '-C', str(ROOT / 'vendor/Pangolin'), 'describe', '--tags', '--exact-match']),
                  topology=topology, affinity=affinity, affinity_basis='WSL lscpu CPU/CORE/SOCKET; one logical CPU per reported core',
                  binary_sha256=links, cmake_flags=caches)
    # Keep the command version separately from CMake flags.
    result['cmake_version'] = run(['cmake', '--version']).splitlines()[0]
    (output / 'environment.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print('PC_ENVIRONMENT_RECORDED binaries=%d affinity=%s' % (len(links), affinity))


if __name__ == '__main__':
    main()
