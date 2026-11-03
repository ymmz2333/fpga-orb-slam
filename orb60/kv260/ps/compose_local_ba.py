"""Native composition of one explicitly bounded local BA graph candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest
from .compile_local_ba_cross import extract

ABI = 'ORB_SLAM3::Optimizer::LocalBundleAdjustment(ORB_SLAM3::KeyFrame*, bool*, ORB_SLAM3::Map*, int&, int&, int&, int&)'


def strongs(path):
    lines = subprocess.check_output(['nm', '-g', '--defined-only', str(path)], text=True).splitlines()
    return {x.split()[2]: x.split()[1] for x in lines if len(x.split()) == 3}


def local_symbol(path):
    found = []
    for name, kind in strongs(path).items():
        if 'LocalBundleAdjustment' in name and subprocess.check_output(['c++filt', name], text=True).strip() == ABI:
            found.append((name, kind))
    if len(found) != 1:
        raise ValueError('Expected one exact local BA ABI')
    return found[0]


def run(root, base, cross, output):
    root, base, cross, output = map(lambda p: Path(p).resolve(), (root, base, cross, output))
    if platform.machine() != 'aarch64':
        raise ValueError('Native KV260 linker required')
    old = json.loads((base / 'BUILD.json').read_text())
    proof = json.loads((cross / 'CROSS_COMPILE.json').read_text())
    if old.get('status') not in ('NATIVE_NEON_POSE_COMPOSITION_PASS', 'NATIVE_MAPPER_SCHEDULING_CANDIDATE_PASS') or proof.get('status') != 'CROSS_LOCAL_BA_COMPILED_REQUIRES_NATIVE_GATES':
        raise ValueError('Explicit reviewed pose and graph builds required')
    original = root / 'slam/src/Optimizer.cc'
    private, body = extract(original.read_bytes().decode(), proof['neighbors'])
    obj = cross / 'LocalBundleAdjustment.o'
    if digest(original) != proof['source_sha256'] or hashlib.sha256(body.encode()).hexdigest() != proof['function_sha256']:
        raise ValueError('Retained local BA source changed')
    if (cross / 'LocalBundleAdjustment.cc').read_bytes() != private.encode() or digest(obj) != proof['object_sha256']:
        raise ValueError('Candidate graph source/object mismatch')
    before = old['products_sha256']
    if any(digest(p) != h for p, h in before.items()):
        raise ValueError('Retained pose products changed')
    liblink = list(old['commands'][-2])
    retained = [(i, Path(x)) for i, x in enumerate(liblink) if x.endswith('RetainedOptimizer.o')]
    if len(retained) != 1:
        raise ValueError('Expected retained optimizer copy in selected pose link')
    index, retained_path = retained[0]
    name, kind = local_symbol(retained_path)
    if kind != 'T' or local_symbol(obj) != (name, 'T'):
        raise ValueError('Local BA strong bindings do not match')
    before = {**before, str(retained_path): digest(retained_path), str(original): digest(original)}
    output.mkdir(parents=True, exist_ok=False)
    for folder in ('lib', 'bin'):
        (output / folder).mkdir()
    weak = output / 'RetainedOptimizer.o'
    lib, exe = output / 'lib/libORB_SLAM3.so', output / 'bin/mono_kv260_network'
    liblink[index] = str(weak)
    liblink.insert(next(i for i, x in enumerate(liblink) if x.endswith('.o')), str(obj))
    liblink[liblink.index('-o') + 1] = str(lib)
    exelink = list(old['commands'][-1])
    oldlib = str(base / 'lib/libORB_SLAM3.so')
    if exelink.count(oldlib) != 1:
        raise ValueError('Selected executable library mismatch')
    exelink[exelink.index(oldlib)] = str(lib)
    exelink[exelink.index('-o') + 1] = str(exe)
    for i, x in enumerate(exelink):
        if x.startswith('-Wl,-rpath,'):
            exelink[i] = '-Wl,-rpath,' + str(lib.parent) + ':' + x.removeprefix('-Wl,-rpath,')
    commands = [['objcopy', '--weaken-symbol=' + name, str(retained_path), str(weak)], liblink, exelink]
    state = dict(status='RUNNING', scope='Different local BA graph configuration; trajectory/DPU/GPU/performance gates remain required',
                 neighbors=proof['neighbors'], max_variable_keyframes=proof['max_variable_keyframes'], cross=proof,
                 commands=commands, protected_sha256=before, base_build_sha256=digest(base / 'BUILD.json'))
    try:
        with (output / 'build.log').open('w') as log:
            for command in commands:
                subprocess.run(command, cwd=root / 'build', stdout=log, stderr=subprocess.STDOUT, check=True)
        previous = strongs(retained_path)
        expected = {**previous, name: 'W'}
        if strongs(weak) != expected:
            raise ValueError('Retained optimizer changed outside selected function binding')
        if any(digest(p) != h for p, h in before.items()):
            raise ValueError('Retained build/source changed')
        deps = subprocess.check_output(['ldd', '-r', str(exe)], text=True, stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps or local_symbol(lib)[1] != 'T':
            raise ValueError('Native local BA link failed')
        state.update(status='NATIVE_LOCAL_BA_COMPOSITION_PASS', dependencies=deps,
                     products_sha256={str(p): digest(p) for p in (lib, exe)})
    except BaseException as error:
        state.update(status='FAILED', error=repr(error))
        raise
    finally:
        (output / 'BUILD.json').write_text(json.dumps(state, indent=2) + '\n')
    print(state['status'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'base', 'cross', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(**vars(p.parse_args()))
