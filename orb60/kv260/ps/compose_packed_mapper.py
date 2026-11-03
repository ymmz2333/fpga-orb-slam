"""Compose the retained PS idle-mapper handoff with exact packed input.

This changes scheduling only. It does not suppress tracking loss, Atlas maps,
keyframes, or local optimization, and is not a whole-video acceptance result.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time
from .build_network_adapter import digest
from .build_pose_variant import available
from .compose_local_ba import strongs

BUILD_STATUS = 'NATIVE_PACKED_IDLE_MAPPER_COMPONENT_PASS'


def transform(entry):
    changes = [
        ('    int tracking_core=-1;',
         '    const bool mapper_barrier=std::getenv("ORB60_MAPPER_BARRIER")&&std::string(std::getenv("ORB60_MAPPER_BARRIER"))=="1";\n    int tracking_core=-1;'),
        ('            auto stats=FeatureIO::Stats();auto& raw=KvNetwork::current();',
         '            const double map_sync_ms=mapper_barrier?slam.WaitForLocalMapping(10000):0;\n            auto stats=FeatureIO::Stats();auto& raw=KvNetwork::current();'),
        ('engine_ns,track_cpu_ms\\n', 'engine_ns,track_cpu_ms,map_sync_ms\\n'),
        ("<<cpu_ms<<'\\n';", "<<cpu_ms<<','<<map_sync_ms<<'\\n';"),
        ('      <<",\\\"tracking_cpu_core\\\":"<<tracking_core',
         '      <<",\\\"mapper_barrier\\\":"<<(mapper_barrier?"true":"false")\n'
         '      <<",\\\"mapper_wait_mode\\\":\\\""<<(mapper_barrier?"idle":"none")<<"\\\""\n'
         '      <<",\\\"tracking_cpu_core\\\":"<<tracking_core'),
    ]
    changed = entry
    for old, new in changes:
        if changed.count(old) != 1:
            raise ValueError('Unreviewed packed-mapper scheduling boundary: ' + old)
        changed = changed.replace(old, new)
    restored = changed
    for old, new in reversed(changes):
        restored = restored.replace(new, old)
    if restored != entry:
        raise ValueError('Unexpected original mapping-body change')
    return changed


def run(root, adapter, base, source_base, mapper, output):
    root, adapter, base, source_base, mapper, output = map(
        lambda p: Path(p).resolve(), (root, adapter, base, source_base, mapper, output))
    if platform.machine() != 'aarch64' or available() < 1536 * 1024:
        raise ValueError('Native KV260 and compile memory margin required')
    old = json.loads((base / 'BUILD.json').read_text())
    src = json.loads((source_base / 'BUILD.json').read_text())
    flags = json.loads((adapter / 'BUILD.json').read_text())
    sync = json.loads((mapper / 'BUILD.json').read_text())
    if (old['status'] != 'NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS' or
        src['status'] != 'NATIVE_PACKED_BMP_COMPONENT_PASS' or
        flags['status'] != 'NATIVE_NETWORK_ADAPTER_BUILD_PASS' or
        sync['status'] != 'NATIVE_MAPPER_SCHEDULING_CANDIDATE_PASS'):
        raise ValueError('Explicit verified packed and mapper bases required')
    before = {**old['products_sha256'], **sync['products_sha256']}
    for folder, manifest in ((source_base, src), (mapper, sync)):
        for name, h in manifest['source_sha256'].items():
            before[str(folder / 'source' / name)] = h
    system = mapper / 'System.o'
    before[str(system)] = digest(system)
    original_system = root / 'slam/src/System.cc'
    if (mapper / 'source/System.cc').read_bytes() != original_system.read_bytes() + b'\n#include "MapperBarrier.inc"\n':
        raise ValueError('Retained System body differs')
    liblink = list(old['link_commands']['library'])
    mainlink = list(old['link_commands']['executable'])
    system_slots = [i for i, x in enumerate(liblink) if x.endswith('/src/System.cc.o')]
    mains = [i for i, x in enumerate(mainlink) if x.endswith('/network.o')]
    libs = [i for i, x in enumerate(mainlink) if x.endswith('/libORB_SLAM3.so')]
    if len(system_slots) != 1 or len(mains) != 1 or len(libs) != 1 or mainlink[libs[0]] != str(base / 'lib/libORB_SLAM3.so'):
        raise ValueError('Unreviewed original composition')
    for command in (liblink, mainlink):
        for value in command:
            if value.endswith('.o'):
                p = Path(value); p = p if p.is_absolute() else root / 'build' / p
                before[str(p)] = digest(p)
    original_object = root / 'build' / liblink[system_slots[0]]
    old_symbols = {k for k, v in strongs(original_object).items() if v == 'T'}
    new_symbols = {k for k, v in strongs(system).items() if v == 'T'}
    added = new_symbols - old_symbols
    if old_symbols - new_symbols or len(added) != 1 or 'WaitForLocalMapping' not in next(iter(added)):
        raise ValueError('System ABI changed outside the scheduling method')
    if any(digest(p) != h for p, h in before.items()):
        raise ValueError('Retained product/source changed')
    output.mkdir(parents=True, exist_ok=False)
    for name in ('source', 'lib', 'bin'):
        (output / name).mkdir()
    for p in (source_base / 'source').iterdir():
        if p.is_file(): (output / 'source' / p.name).write_bytes(p.read_bytes())
    for name in ('System.h', 'MapperBarrier.inc', 'System.cc'):
        (output / 'source' / name).write_bytes((mapper / 'source' / name).read_bytes())
    entry = output / 'source/mono_kv260_network.cc'
    entry.write_text(transform(entry.read_text()))
    common = list(flags['commands'][0]); common = common[:common.index('-c')]
    common = [common[0], '-I' + str(output / 'source'), '-include',
              str(output / 'source/Orb60Protocol.h'), *common[1:]]
    obj = output / 'network.o'; lib = output / 'lib/libORB_SLAM3.so'
    exe = output / 'bin/mono_kv260_network'
    liblink[system_slots[0]] = str(system)
    liblink[liblink.index('-o') + 1] = str(lib)
    mainlink[mains[0]] = str(obj); mainlink[libs[0]] = str(lib)
    mainlink[mainlink.index('-o') + 1] = str(exe)
    for i, x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):
            mainlink[i] = '-Wl,-rpath,' + str(lib.parent) + ':' + x.removeprefix('-Wl,-rpath,')
    commands = [[*common, '-c', str(entry), '-o', str(obj)], liblink, mainlink]
    state = dict(status='RUNNING', scope=__doc__, commands=commands,
                 protected_sha256=before, mapper_wait_mode='idle',
                 source_sha256={p.name: digest(p) for p in (output / 'source').iterdir()},
                 link_commands=dict(library=liblink, executable=mainlink),
                 original_tracking_solver_and_mapping_objects_retained=True)
    try:
        with (output / 'build.log').open('w') as log:
            for command in commands:
                child = subprocess.Popen(command, cwd=root / 'build', stdout=log,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    while child.poll() is None:
                        if available() < 256 * 1024:
                            os.killpg(child.pid, signal.SIGTERM); child.wait(timeout=10)
                            raise MemoryError('Owned compiler stopped below256MiB available')
                        time.sleep(.5)
                    if child.returncode: raise subprocess.CalledProcessError(child.returncode, command)
                finally:
                    if child.poll() is None: os.killpg(child.pid, signal.SIGKILL); child.wait()
        deps = subprocess.check_output(['ldd', '-r', str(exe)], text=True, stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:
            raise ValueError('Private mapper runtime dependency mismatch')
        if any(digest(p) != h for p, h in before.items()):
            raise ValueError('Retained product changed during composition')
        state.update(status=BUILD_STATUS, dependencies=deps,
                     products_sha256={str(p): digest(p) for p in (lib, exe)})
    except BaseException as error:
        state.update(status='FAILED', error=repr(error)); raise
    finally:
        (output / 'BUILD.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(dict(status=state['status'], mapper_wait_mode='idle')), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'adapter', 'base', 'source_base', 'mapper', 'output'):
        p.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    run(**vars(p.parse_args()))
