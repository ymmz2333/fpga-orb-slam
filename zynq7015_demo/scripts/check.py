"""Serial native software build and bounded tests. Never invokes FPGA tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
from resource_guard import require_local_memory,ResourceDeferred
from jpeg_dependency import ensure_jpeg,verify_camera_fixtures

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--compiler', type=Path, default=Path('C:/Users/dmsun/mingw/mingw64/bin/g++.exe'))
parser.add_argument('--build-only', action='store_true')
args = parser.parse_args()
compiler = args.compiler.resolve()
if not compiler.is_file():
    raise SystemExit('Native compiler missing: ' + str(compiler))
out = ROOT / 'build/native'
out.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
system = env.get('SystemRoot', 'C:/Windows')
env['PATH'] = str(compiler.parent) + ';' + system + '/System32;' + system
sources = ['math', 'pnp', 'slam', 'map_store', 'formats', 'ui', 'camera', 'ports']
flags = ['-std=c++17', '-pthread', '-O0', '-g0', '-Wall', '-Wextra', '-Wno-misleading-indentation', '-I' + str(ROOT / 'include'), '-I' + str(ROOT / 'interfaces')]
header_files = sorted((ROOT / 'include').rglob('*.hpp')) + sorted((ROOT / 'interfaces').glob('*.h'))
header_files += sorted((ROOT / 'vendor/opencv_p3p').glob('*.cpp'))+sorted((ROOT / 'vendor/opencv_p3p').glob('*.h'))
header_hash = hashlib.sha256(b''.join(p.read_bytes() for p in header_files)).digest()
results = []


def run(command, name, timeout=90):
    require_local_memory(name)
    log = out / (name + '.log')
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run([str(v) for v in command], cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    results.append(dict(command=[str(v) for v in command], returncode=result.returncode, log=str(log)))
    if result.returncode:
        print(log.read_text(encoding='utf-8', errors='replace'), flush=True)
        raise RuntimeError('Failed: ' + name)
    print('PASS', name, flush=True)


try:
    verify_camera_fixtures()
    jpeg=ensure_jpeg('native')
    flags+=['-I'+str(jpeg['include'])]
    provenance = json.loads((ROOT / 'vendor/orb_engine/provenance.json').read_text(encoding='utf-8-sig'))
    for entry in provenance:
        actual = hashlib.sha256((ROOT / 'vendor/orb_engine' / entry['Path']).read_bytes()).hexdigest()
        if actual != entry['SHA256']:
            raise RuntimeError('Frozen ORB engine changed: ' + entry['Path'])
    print('PASS frozen_orb_engine_hashes', flush=True)
    for name, path in [(s, ROOT / 'src' / (s + '.cpp')) for s in sources] + [('main', ROOT / 'src/main.cpp'), ('test', ROOT / 'tests/test_slam.cpp')]:
        digest = hashlib.sha256(path.read_bytes() + header_hash + str(flags).encode()+hashlib.sha256(compiler.read_bytes()).digest()).hexdigest()
        stamp, obj = out / (name + '.sha256'), out / (name + '.o')
        if not obj.exists() or not stamp.exists() or stamp.read_text() != digest:
            run([compiler, *flags, '-c', path, '-o', obj], 'compile_' + name)
            stamp.write_text(digest)
    objects = [out / (s + '.o') for s in sources]
    for name, main in [('zynq-slam', 'main'), ('test-zslam', 'test')]:
        run([compiler, '-pthread', *objects, out / (main + '.o'), jpeg['library'], '-o', out / (name + '.exe')], 'link_' + name)
    if not args.build_only:
        shutil.copytree(ROOT/'tests/fixtures/camera',out/'test-fixtures/camera',dirs_exist_ok=True)
        run([out / 'test-zslam.exe', out], 'unit_tests', 60)
        print((out / 'unit_tests.log').read_text(), flush=True)
    paths=sorted((ROOT/'src').glob('*.cpp'))+header_files+[ROOT/'tests/test_slam.cpp']+sorted((ROOT/'tests/fixtures/camera').glob('*'))
    report = dict(status='PASS', scope='Native software only; no synthesis, implementation or board execution', checks=results,input_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},jpeg_dependency=str(jpeg['report']),tests_run=not args.build_only)
except ResourceDeferred as error:
    report = dict(status='DEFERRED_MEMORY',error=str(error),checks=results)
    print(str(error),flush=True)
    raise SystemExit(75)
except Exception as error:
    report = dict(status='FAIL', error=str(error), checks=results)
    raise
finally:
    (out / 'checks.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
