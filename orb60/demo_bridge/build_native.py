"""Serial, memory-guarded host build; never programs hardware or uses WSL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
ZYNQ = ROOT.parent / 'zynq7015_demo'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--compiler', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT / 'build/demo_bridge/native')
    a = p.parse_args()
    sys.path.insert(0, str(ZYNQ / 'scripts'))
    from resource_guard import require_local_memory
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    upstream = ROOT.parent / 'zynq7015_usb_slam_20261024/source'
    jpeg = upstream / 'build/jpeg_native_757f3a7b25972eaa'
    library = jpeg / 'libturbojpeg.a'
    if library.is_file():
        provenance = json.loads((jpeg / 'checks.json').read_text())
        expected=provenance['library_sha256'] if provenance['status']=='PASS' else ''
    else:
        library=Path(__file__).parent/'dependencies/libturbojpeg-native.a'
        expected=json.loads((library.parent/'provenance.json').read_text())[library.name]['sha256']
    if hashlib.sha256(library.read_bytes()).hexdigest() != expected:
        raise ValueError('Pinned native JPEG library integrity failed')
    flags = ['-std=c++17', '-pthread', '-O2', '-g0', '-Wall', '-Wextra', '-Wno-misleading-indentation',
             '-I' + str(ZYNQ / 'include'), '-I' + str(ZYNQ / 'interfaces'),
             '-I' + str(ZYNQ / 'vendor/jpeg_turbo/upstream/src')]
    env = os.environ.copy()
    env['PATH'] = str(a.compiler.parent) + os.pathsep + env.get('PATH', '')
    common = ['math', 'pnp', 'slam', 'map_store', 'formats', 'ui', 'camera', 'ports']
    sources = [(name, ZYNQ / 'src' / (name + '.cpp')) for name in common]
    sources += [('demo_main', ZYNQ / 'src/demo_main.cpp'), ('test_slam', ZYNQ / 'tests/test_slam.cpp'),
                ('test_bridge', Path(__file__).parent / 'tests/test_bridge.cpp'),
                ('map_install', Path(__file__).parent / 'map_install.cpp')]
    headers = sorted((ZYNQ / 'include').rglob('*.hpp')) + sorted((ZYNQ / 'interfaces').glob('*.h'))
    signature = str(flags).encode() + hashlib.sha256(a.compiler.read_bytes()).digest()
    includes = [ZYNQ / 'include', ZYNQ / 'interfaces', ZYNQ / 'vendor/jpeg_turbo/upstream/src']
    def dependencies(path, seen=None):
        seen = set() if seen is None else seen
        path = path.resolve()
        if path in seen:
            return b''
        seen.add(path)
        data = path.read_bytes()
        result = data
        for name in re.findall(rb'^\s*#\s*include\s*"([^"]+)"', data, re.M):
            for directory in [path.parent, *includes]:
                candidate = directory / name.decode()
                if candidate.is_file():
                    result += dependencies(candidate, seen)
                    break
        return result
    checks = []
    def run(command, name):
        available = require_local_memory(name)
        with (out / (name + '.log')).open('w') as f:
            result = subprocess.run(list(map(str, command)), env=env, stdout=f, stderr=subprocess.STDOUT, timeout=240)
        checks.append(dict(name=name, returncode=result.returncode, available_mib=available))
        if result.returncode:
            print((out / (name + '.log')).read_text(errors='replace')[-8000:])
            raise RuntimeError('Failed ' + name)
        print('PASS', name, flush=True)
    report = dict(scope='Native software only; no ARM/RK/board/HDMI acceptance', status='RUNNING', checks=checks)
    try:
        for name, path in sources:
            digest = hashlib.sha256(signature + dependencies(path)).hexdigest()
            obj, stamp = out / (name + '.o'), out / (name + '.sha256')
            if not obj.exists() or not stamp.exists() or stamp.read_text() != digest:
                run([a.compiler, *flags, '-c', path, '-o', obj], 'compile_' + name)
                stamp.write_text(digest)
        objects = [out / (name + '.o') for name in common]
        for exe, entry in [('zynq-demo', 'demo_main'), ('test-zslam', 'test_slam'), ('test-bridge', 'test_bridge'), ('zynq-map-install', 'map_install')]:
            run([a.compiler, '-pthread', '-static', *objects, out / (entry + '.o'), library, '-lws2_32', '-o', out / (exe + '.exe')], 'link_' + exe)
        shutil.copytree(ZYNQ / 'tests/fixtures/camera', out / 'test-fixtures/camera', dirs_exist_ok=True)
        report['status'] = 'PASS'
        report['compiler'] = subprocess.check_output([a.compiler, '--version'], env=env).decode(errors='replace').splitlines()[0]
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        (out / 'checks.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
