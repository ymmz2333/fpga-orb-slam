"""Compile only an isolated network main against an explicitly verified PS library."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import time
from .build_network_adapter import digest


def run(root,adapter,output):
    root,adapter,output=map(lambda p:Path(p).resolve(),(root,adapter,output))
    if platform.machine()!='aarch64':raise ValueError('Native KV260 required')
    free=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))
    if free<1536*1024:raise ValueError('At least1536MiB available memory required')
    base=json.loads((adapter/'BUILD.json').read_text())
    if base['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS':raise ValueError('Verified native network adapter required')
    for p,h in base['products_sha256'].items():
        if digest(p)!=h:raise ValueError('Adapter changed')
    output.mkdir(parents=True,exist_ok=False);(output/'source').mkdir();(output/'bin').mkdir()
    src=Path(__file__).resolve().parent/'mono_kv260_network.cc';private=output/'source/mono_kv260_network.cc';private.write_bytes(src.read_bytes())
    command=list(base['commands'][2]);command[command.index('-c')+1]=str(private);command[command.index('-o')+1]=str(output/'network.o')
    link=list(base['commands'][3]);old=str(adapter/'network.o')
    if link.count(old)!=1:raise ValueError('Original main object mismatch')
    link[link.index(old)]=str(output/'network.o');link[link.index('-o')+1]=str(output/'bin/mono_kv260_network')
    state=dict(status='RUNNING',scope='New producer/telemetry entry; retained O2 SLAM math and FeatureIO reused',
               source_sha256=digest(src),commands=[command,link],started_monotonic_ns=time.monotonic_ns())
    try:
        with (output/'build.log').open('w') as log:
            for item in state['commands']:subprocess.run(item,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
        for p,h in base['products_sha256'].items():
            if digest(p)!=h:raise ValueError('Retained adapter product changed')
        binary=output/'bin/mono_kv260_network';deps=subprocess.check_output(['ldd',str(binary)],text=True)
        if 'ARM aarch64' not in subprocess.check_output(['file',str(binary)],text=True) or 'not found' in deps:
            raise ValueError('ARM64 ELF/link check failed')
        state.update(status='NATIVE_NETWORK_ENTRY_BUILD_PASS',dependencies=deps,
                     products_sha256={str(binary):digest(binary),str(adapter/'lib/libORB_SLAM3.so'):digest(adapter/'lib/libORB_SLAM3.so')})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:state['finished_monotonic_ns']=time.monotonic_ns();(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','adapter','output'):p.add_argument('--'+name,type=Path,required=True)
    run(**vars(p.parse_args()))
