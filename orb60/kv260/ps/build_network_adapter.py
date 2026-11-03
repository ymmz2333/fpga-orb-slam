"""Build an isolated native 7015-network executable using retained PS objects."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import subprocess
import time


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.root.resolve();out=a.output.resolve();build=root/'build';slam=root/'slam'
    if platform.machine()!='aarch64':raise ValueError('Actual native KV260 compiler required')
    out.mkdir(parents=True,exist_ok=False);(out/'lib').mkdir();(out/'bin').mkdir();(out/'source').mkdir()
    authored=Path(__file__).resolve().parent
    for name in ('Kv260NetworkRecord.h','Kv260VideoPipeline.h','mono_kv260_network.cc'):
        (out/'source'/name).write_bytes((authored/name).read_bytes())
    feature=(slam/'src/FeatureIO.cc').read_text();pipeline=(slam/'include/FpgaPipeline.h').read_text()
    anchor='        decode(f.payload,f.count,extractor,keys,descriptors,decode_ms);'
    if pipeline.count(anchor)!=1:raise ValueError('Unsupported retained pipeline instrumentation anchor')
    pipeline=pipeline.replace('#include "FpgaORB.h"','#include "FpgaORB.h"\n#include "Kv260NetworkRecord.h"')
    pipeline=pipeline.replace(anchor,anchor+'\n        KvNetwork::observe(timestamp,f.payload,f.count,keys);')
    # Quoted includes resolve beside this private FeatureIO translation unit.
    (out/'source/FeatureIO.cc').write_text(feature)
    (out/'source/FpgaPipeline.h').write_text(pipeline)
    flags={}
    for line in (build/'CMakeFiles/ORB_SLAM3.dir/flags.make').read_text().splitlines():
        if ' = ' in line:
            key,value=line.split(' = ',1);flags[key]=shlex.split(value)
    if flags.get('CXX_FLAGS')!=['-O2','-DNDEBUG','-fPIC','-std=gnu++14']:raise ValueError('Unreviewed retained compiler flags')
    compiler=shlex.split((build/'CMakeFiles/ORB_SLAM3.dir/link.txt').read_text())[0]
    common=[compiler,'-I'+str(out/'source'),*flags['CXX_DEFINES'],*flags['CXX_INCLUDES'],*flags['CXX_FLAGS']]
    liblink=shlex.split((build/'CMakeFiles/ORB_SLAM3.dir/link.txt').read_text())
    exelink=shlex.split((build/'CMakeFiles/mono_kv260.dir/link.txt').read_text())
    old_obj='CMakeFiles/ORB_SLAM3.dir/src/FeatureIO.cc.o'
    if liblink.count(old_obj)!=1:raise ValueError('Retained FeatureIO object is ambiguous')
    liblink[liblink.index(old_obj)]=str(out/'FeatureIO.o')
    liblink[liblink.index('-o')+1]=str(out/'lib/libORB_SLAM3.so')
    old_main='CMakeFiles/mono_kv260.dir/Examples/Monocular/mono_kv260.cc.o'
    if exelink.count(old_main)!=1 or exelink.count('lib/libORB_SLAM3.so')!=1:raise ValueError('Unsupported retained executable link')
    exelink[exelink.index(old_main)]=str(out/'network.o')
    exelink[exelink.index('lib/libORB_SLAM3.so')]=str(out/'lib/libORB_SLAM3.so')
    exelink[exelink.index('-o')+1]=str(out/'bin/mono_kv260_network')
    for i,value in enumerate(exelink):
        if value.startswith('-Wl,-rpath,'):exelink[i]='-Wl,-rpath,'+str(out/'lib')+':'+value.removeprefix('-Wl,-rpath,')
    commands=[[*common,'-c',str(out/'source/FeatureIO.cc'),'-o',str(out/'FeatureIO.o')],liblink,
              [*common,'-c',str(out/'source/mono_kv260_network.cc'),'-o',str(out/'network.o')],exelink]
    before={str(x):digest(x) for x in build.rglob('*.o')}
    state=dict(status='RUNNING',started=time.time(),commands=commands,
               source_sha256={x.name:digest(x) for x in (out/'source').iterdir()},
               retained_library_before=digest(build/'lib/libORB_SLAM3.so'))
    try:
        with (out/'build.log').open('w') as log:
            for command in commands:
                log.write('\nCOMMAND '+shlex.join(command)+'\n');log.flush()
                subprocess.run(command,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
        if any(digest(path)!=old for path,old in before.items()):raise ValueError('Retained object unexpectedly changed')
        if state['retained_library_before']!=digest(build/'lib/libORB_SLAM3.so'):raise ValueError('Retained library changed')
        products=[out/'bin/mono_kv260_network',out/'lib/libORB_SLAM3.so']
        abi=subprocess.check_output(['file',*[str(x) for x in products]],text=True)
        deps=subprocess.check_output(['ldd',str(products[0])],text=True)
        if abi.count('ARM aarch64')!=2 or 'not found' in deps:raise ValueError('Native ELF/link validation failed')
        state.update(status='NATIVE_NETWORK_ADAPTER_BUILD_PASS',products_sha256={str(x):digest(x) for x in products},architecture=abi,dependencies=deps)
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:state['finished']=time.time();(out/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':main()
