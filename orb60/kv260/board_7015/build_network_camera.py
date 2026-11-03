"""Serial ARM PS build and native socket test binary, using the pinned JPEG ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(source,output):
    source,output=Path(source).resolve(),Path(output).resolve()
    if platform.machine()!='aarch64':raise ValueError('Use native KV260 host with the ARMv7 cross compiler; no WSL')
    output.mkdir(parents=True,exist_ok=False);(output/'bin').mkdir();(output/'objects').mkdir()
    project=source/'zynq7015_demo';jpeg=source/'orb60/demo_bridge/dependencies/libturbojpeg-arm.a'
    if sha(jpeg)!='3eb4d8caa63dafb39a1fc249332d580c91e357a902c5b56ed9696c9f11bdd6ef':
        raise ValueError('Pinned verified ARM JPEG archive changed')
    for entry in json.loads((project/'vendor/orb_engine/provenance.json').read_text(encoding='utf-8-sig')):
        if sha(project/'vendor/orb_engine'/entry['Path'])!=entry['SHA256']:raise ValueError('Frozen PL engine interface changed')
    manifest=json.loads((source/'SOURCE_SHA256.json').read_text())
    for name,h in manifest.items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or sha(source/p)!=h:raise ValueError('Source payload changed/unsafe: '+name)
    cxx=shutil.which('arm-linux-gnueabihf-g++');cc=shutil.which('arm-linux-gnueabihf-gcc');native=shutil.which('g++')
    if not all((cxx,cc,native)):raise ValueError('Explicit native and ARM cross toolchains required')
    includes=['-I'+str(project/'include'),'-I'+str(project/'interfaces'),'-I'+str(project/'vendor/orb_engine'),
              '-I'+str(project/'vendor/jpeg_turbo/upstream/src')]
    common=['-std=c++17','-O2','-g0','-pthread','-Wall','-Wextra','-Wno-misleading-indentation',*includes]
    arm=['-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard']
    commands=[]
    commands.append([native,*common,str(project/'src/network_camera.cpp'),str(project/'tools/test_network_camera.cpp'),'-o',str(output/'bin/test_network_camera_host')])
    objects=[]
    for name in ('math','pnp','slam','map_store','formats','ui','camera','ports','demo_main','network_camera'):
        obj=output/'objects'/(name+'.o');objects.append(obj)
        commands.append([cxx,*common,*arm,'-c',str(project/'src'/(name+'.cpp')),'-o',str(obj)])
    engine=output/'objects/engine.o'
    commands.append([cc,'-std=c11','-O2',*arm,'-I'+str(project/'vendor/orb_engine'),'-c',str(project/'vendor/orb_engine/engine.c'),'-o',str(engine)])
    link=[cxx,*arm,'-static','-pthread',*map(str,objects),str(engine),str(jpeg),'-Wl,--whole-archive','-lpthread','-Wl,--no-whole-archive','-o',str(output/'bin/zynq-demo')]
    commands.append(link)
    # The geometry suite uses the same fully rebuilt common sources.
    test_obj=output/'objects/test_slam.o'
    commands.append([cxx,*common,*arm,'-c',str(project/'tests/test_slam.cpp'),'-o',str(test_obj)])
    retained=[p for p in objects if p.stem not in ('demo_main','network_camera')]
    commands.append([cxx,*arm,'-static','-pthread',*map(str,retained),str(test_obj),str(engine),str(jpeg),'-Wl,--whole-archive','-lpthread','-Wl,--no-whole-archive','-o',str(output/'bin/test-zslam')])
    state=dict(status='RUNNING',scope=__doc__,commands=commands,source_sha256=manifest,compiler=subprocess.check_output([cxx,'--version'],text=True).splitlines()[0],
               started_monotonic_ns=time.monotonic_ns(),hardware_programmed=False)
    try:
        for i,command in enumerate(commands):
            available=int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:')))
            if available<1536*1024:raise MemoryError('1536MiB available compiler memory required')
            with (output/('compile_%02d.log'%i)).open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            print('PS_BUILD_STEP',i+1,len(commands),flush=True)
        for name in ('zynq-demo','test-zslam'):
            description=subprocess.check_output(['file',str(output/'bin'/name)],text=True)
            if 'ARM' not in description or 'statically linked' not in description:raise ValueError('Fully static ARM PS executable required')
        if any(sha(source/p)!=h for p,h in manifest.items()):raise ValueError('Source changed during build')
        state.update(status='ARM_NETWORK_CAMERA_PS_BUILD_PASS',products_sha256={p.name:sha(p) for p in (output/'bin').iterdir()})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(state['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
