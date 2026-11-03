"""PC-only bounded local-BA candidate; native map/trajectory gates are separate."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from .build_network_adapter import digest

SIGNATURE = 'void Optimizer::LocalBundleAdjustment(KeyFrame *pKF'
FOLLOWING = 'void Optimizer::OptimizeEssentialGraph(Map* pMap'
ORIGINAL_SELECTION = 'pKF->GetVectorCovisibleKeyFrames()'


def extract(source, neighbors):
    if isinstance(neighbors, bool) or neighbors not in (5, 10, 20):
        raise ValueError('Explicit reviewed local window required: 5,10,20')
    if source.count(SIGNATURE) != 1 or source.count(FOLLOWING) != 1:
        raise ValueError('Unreviewed retained optimizer boundary')
    start = source.index(SIGNATURE)
    end = source.index(FOLLOWING, start)
    body = source[start:end].rstrip()
    if not body.endswith('}') or body.count('Optimizer::') != 1 or body.count(ORIGINAL_SELECTION) != 1:
        raise ValueError('Ambiguous retained local BA function')
    selected = 'pKF->GetBestCovisibilityKeyFrames(%d)' % neighbors
    changed = body.replace(ORIGINAL_SELECTION, selected)
    if changed.replace(selected, ORIGINAL_SELECTION) != body:
        raise ValueError('Local BA changed outside its neighbor selection')
    prefix = source[:source.index('namespace ORB_SLAM3')]
    if prefix.count('#include "Optimizer.h"') != 1:
        raise ValueError('Unreviewed optimizer include boundary')
    return prefix + 'namespace ORB_SLAM3 {\n' + changed + '\n}\n', body


def run(compiler_manifest, sysroot, output, neighbors):
    compiler_manifest, sysroot, output = map(lambda p: Path(p).resolve(), (compiler_manifest, sysroot, output))
    if platform.machine() != 'x86_64':
        raise ValueError('PC cross-build host required')
    base = json.loads(compiler_manifest.read_text())
    if base.get('status') != 'CROSS_OBJECT_COMPILED_REQUIRES_NATIVE_LINK_AND_BOARD_GATES':
        raise ValueError('Verified explicit cross compiler manifest required')
    source = sysroot / 'slam/src/Optimizer.cc'
    if digest(source) != base['source_sha256']:
        raise ValueError('Retained optimizer changed')
    private, body = extract(source.read_bytes().decode(), neighbors)
    common = base['command'][:base['command'].index('-c')]
    if digest(common[0]) != base['compiler_sha256'] or any(x in common for x in ('-Ofast', '-ffast-math')):
        raise ValueError('Compiler or floating-point policy mismatch')
    if '--sysroot=' + str(sysroot) not in common:
        raise ValueError('Explicit matching sysroot required')
    output.mkdir(parents=True, exist_ok=False)
    private_path = output / 'LocalBundleAdjustment.cc'
    private_path.write_bytes(private.encode())
    obj = output / 'LocalBundleAdjustment.o'
    command = [*common, '-c', str(private_path), '-o', str(obj)]
    state = dict(status='RUNNING', scope='Different local BA graph configuration, not a same-condition acceleration or native acceptance',
                 neighbors=neighbors, max_variable_keyframes=neighbors + 1,
                 fixed_observing_cameras_retained=True, iterations_and_outlier_thresholds_unchanged=True,
                 source_sha256=digest(source), function_sha256=hashlib.sha256(body.encode()).hexdigest(),
                 private_source_sha256=digest(private_path), compiler_manifest_sha256=digest(compiler_manifest),
                 command=command, selection_only_change=True)
    try:
        with (output / 'build.log').open('w') as log:
            subprocess.run(['/usr/bin/time', '-v', '-o', str(output / 'resources.txt'), *command],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        abi = subprocess.check_output(['file', str(obj)], text=True)
        if 'ARM aarch64' not in abi:
            raise ValueError('Wrong object architecture')
        state.update(status='CROSS_LOCAL_BA_COMPILED_REQUIRES_NATIVE_GATES', architecture=abi, object_sha256=digest(obj))
    except BaseException as error:
        state.update(status='FAILED', error=repr(error))
        raise
    finally:
        (output / 'CROSS_COMPILE.json').write_text(json.dumps(state, indent=2) + '\n')
    print(state['status'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('compiler-manifest', 'sysroot', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--neighbors', type=int, choices=(5, 10, 20), required=True)
    run(**vars(p.parse_args()))
