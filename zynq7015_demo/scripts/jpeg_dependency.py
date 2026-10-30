"""Build pinned libjpeg-turbo separately, serially, with per-compiler RAM guards."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
from resource_guard import require_local_memory,ResourceDeferred
ROOT=Path(__file__).resolve().parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def verify_camera_fixtures():
    folder=ROOT/'tests/fixtures/camera';manifest=json.loads((folder/'manifest.json').read_text())
    for name,expected in manifest['sha256'].items():
        if Path(name).name!=name or digest(folder/name)!=expected:raise RuntimeError('Camera fixture missing/modified: '+name)
def ensure_jpeg(target):
    if target not in ('native','arm'):raise ValueError('Invalid JPEG target')
    src=ROOT/'vendor/jpeg_turbo/upstream';provenance=ROOT/'vendor/jpeg_turbo/provenance.json'
    meta=json.loads(provenance.read_text())
    for name,sha in meta['source_sha256'].items():
        if digest(src/name)!=sha:raise RuntimeError('Frozen JPEG source differs: '+name)
    compiler=Path('C:/Users/dmsun/mingw/mingw64/bin/gcc.exe') if target=='native' else Path('C:/Xilinx/SDK/2018.3/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin/arm-linux-gnueabihf-gcc.exe')
    cmake=ROOT/'build/tools/cmake/cmake-3.31.10-windows-x86_64/bin/cmake.exe';ninja=ROOT/'build/tools/ninja/ninja.exe'
    inputs={str(p.relative_to(ROOT)):digest(p) for p in [provenance,Path(__file__),ROOT/'scripts/guarded_compiler.py',ROOT/'scripts/resource_guard.py']}
    inputs.update({str((src/name).relative_to(ROOT)):sha for name,sha in meta['source_sha256'].items()})
    signature=dict(target=target,input_sha256=inputs,compiler_sha256=digest(compiler),cmake_sha256=digest(cmake),ninja_sha256=digest(ninja))
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
    out=ROOT/'build'/('jpeg_'+target+'_'+key);out.mkdir(parents=True,exist_ok=True)
    report_path=out/'checks.json';lib=out/'libturbojpeg.a'
    if report_path.exists():
        old=json.loads(report_path.read_text())
        if old['status']=='PASS' and old['signature']==signature and lib.is_file() and digest(lib)==old['library_sha256']:
            return dict(include=src/'src',library=lib,report=report_path,inputs=inputs,signature=signature)
    report=dict(status='RUNNING',signature=signature,commands=[],library=str(lib),upstream_version='3.2.0',scope='JPEG static library; no camera/hardware verification')
    env=os.environ.copy();system=Path(env.get('SystemRoot','C:/Windows'))
    env['PATH']=';'.join(map(str,[compiler.parent,cmake.parent,ninja.parent,system/'System32',system]))
    env['CMAKE_BUILD_PARALLEL_LEVEL']='1'
    wrapper=out/'guarded-gcc.cmd'
    wrapper.write_text('@echo off\r\n"'+str(Path(sys.executable).resolve())+'" "'+str(ROOT/'scripts/guarded_compiler.py')+'" "'+str(compiler)+'" %*\r\nexit /b %ERRORLEVEL%\r\n',encoding='ascii')
    args=[str(cmake),'-S',str(src),'-B',str(out),'-G','Ninja','-DCMAKE_MAKE_PROGRAM='+str(ninja),'-DCMAKE_C_COMPILER='+str(wrapper),
          '-DCMAKE_ASM_COMPILER='+str(wrapper),'-DCMAKE_BUILD_TYPE=Release','-DENABLE_SHARED=OFF','-DENABLE_STATIC=ON',
          '-DWITH_TURBOJPEG=ON','-DWITH_TOOLS=OFF','-DWITH_TESTS=OFF','-DWITH_SIMD='+('ON' if target=='arm' else 'OFF')]
    prefix='arm-linux-gnueabihf-' if target=='arm' else ''
    for variable,tool in [('AR','ar'),('RANLIB','ranlib'),('LINKER','ld'),('NM','nm'),('OBJDUMP','objdump')]:args+=['-DCMAKE_'+variable+'='+str(compiler.parent/(prefix+tool+'.exe'))]
    if target=='arm':args+=['-DCMAKE_SYSTEM_NAME=Linux','-DCMAKE_SYSTEM_PROCESSOR=arm','-DCMAKE_C_FLAGS=-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard','-DCMAKE_ASM_FLAGS=-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard','-DREQUIRE_SIMD=ON']
    try:
        for name,command in [('configure',args),('build',[str(cmake),'--build',str(out),'--target','turbojpeg-static','--parallel','1'])]:
            require_local_memory('jpeg '+name);log=out/(name+'.log')
            with log.open('w') as f:rc=subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=1200).returncode
            report['commands'].append(dict(name=name,command=command,returncode=rc,log=str(log)))
            if rc:
                text=log.read_text(errors='replace')
                if 'DEFERRED_MEMORY' in text:raise ResourceDeferred('DEFERRED_MEMORY JPEG '+name+'; objects retained in '+str(out))
                print(text[-10000:],flush=True);raise RuntimeError('JPEG '+name+' failed')
        if not lib.is_file():raise RuntimeError('JPEG static archive missing: '+str(lib))
        report.update(status='PASS',library_sha256=digest(lib),simd='ARM NEON' if target=='arm' else 'scalar native verification')
    except ResourceDeferred as error:
        report.update(status='DEFERRED_MEMORY',error=str(error));raise
    except Exception as error:
        report.update(status='FAIL',error=str(error));raise
    finally:report_path.write_text(json.dumps(report,indent=2)+'\n')
    return dict(include=src/'src',library=lib,report=report_path,inputs=inputs,signature=signature)
if __name__=='__main__':
    try:print(ensure_jpeg(sys.argv[1]))
    except ResourceDeferred as error:print(error,flush=True);raise SystemExit(75)
