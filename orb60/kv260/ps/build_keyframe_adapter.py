"""Bounded native incremental build against hash-verified retained PS objects.

The board's original objects predate its corrected system clock. CMake's newly
dated flags file otherwise rebuilds every unchanged, large optimizer unit.
Compile the two changed translation units with their actual CMake rules, then
execute the generated link commands. No source/flag/acceptance weakening.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('baseline',type=Path);parser.add_argument('run',type=Path)
    args=parser.parse_args();root=args.root.resolve();build=root/'build';source=root/'slam';run=args.run.resolve()
    if platform.machine()!='aarch64':raise RuntimeError('Native AArch64 compiler required')
    run.mkdir(parents=True,exist_ok=False)
    expected=json.loads(args.baseline.read_text());changed=[]
    for name,old in expected.items():
        if digest(source/name)!=old:changed.append(name)
    if set(changed)!={'src/Tracking.cc','Examples/Monocular/mono_kv260.cc'}:
        raise ValueError('Unreviewed source changes prevent retained-object reuse: '+repr(changed))
    flags=(build/'CMakeFiles/ORB_SLAM3.dir/flags.make').read_text()
    if 'CXX_FLAGS = -O2 -DNDEBUG -fPIC -std=gnu++14' not in flags or '-DREGISTER_TIMES' not in flags:
        raise ValueError('Unexpected compilation configuration')
    before={str(p.relative_to(build)):digest(p) for p in build.rglob('*.o')}
    steps=[
        ['make','-f','CMakeFiles/ORB_SLAM3.dir/build.make','CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o'],
        ['cmake','-E','cmake_link_script','CMakeFiles/ORB_SLAM3.dir/link.txt','--verbose=1'],
        ['make','-f','CMakeFiles/mono_kv260.dir/build.make','CMakeFiles/mono_kv260.dir/Examples/Monocular/mono_kv260.cc.o'],
        ['cmake','-E','cmake_link_script','CMakeFiles/mono_kv260.dir/link.txt','--verbose=1']]
    report=dict(status='RUNNING',started=time.time(),changed_sources=changed,commands=steps,objects_before=before)
    try:
        with (run/'console.log').open('w') as log:
            for command in steps:
                log.write('\nCOMMAND '+repr(command)+'\n');log.flush()
                subprocess.run(command,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
        after={str(p.relative_to(build)):digest(p) for p in build.rglob('*.o')}
        allowed={'CMakeFiles/ORB_SLAM3.dir/src/Tracking.cc.o','CMakeFiles/mono_kv260.dir/Examples/Monocular/mono_kv260.cc.o'}
        if any(before.get(k)!=v for k,v in after.items() if k not in allowed):
            raise ValueError('An unmodified object unexpectedly changed')
        products=[build/'bin/mono_kv260',build/'lib/libORB_SLAM3.so']
        architecture=subprocess.check_output(['file',*[str(p) for p in products]],text=True)
        dependencies=subprocess.check_output(['ldd',str(products[0])],text=True)
        if architecture.count('ARM aarch64')!=2 or 'not found' in dependencies:raise ValueError('Native ABI/link failure')
        (run/'architecture.txt').write_text(architecture);(run/'dependencies.txt').write_text(dependencies)
        report.update(status='NATIVE_KEYFRAME_ADAPTER_INCREMENTAL_PASS',exit_code=0,
                      products_sha256={str(p):digest(p) for p in products},objects_after=after,
                      flags=flags,compiler=subprocess.check_output(['g++','--version'],text=True))
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        report['finished']=time.time();(run/'state.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],flush=True)


if __name__=='__main__':main()
