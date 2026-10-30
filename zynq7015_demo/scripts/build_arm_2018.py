"""Serial ARM Linux cross-build with the installed SDK 2018.3 GCC profile.

Builds the app and board self-test, but never executes ARM binaries or hardware.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from resource_guard import require_local_memory,ResourceDeferred
from jpeg_dependency import ensure_jpeg,verify_camera_fixtures

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path('C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/zynq-arm-linux-2018.3.cmd')
COMPILER_BIN = Path('C:/Xilinx/SDK/2018.3/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin')
PREFIX = 'arm-linux-gnueabihf-'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',type=Path,help='Continue an unchanged DEFERRED_MEMORY build')
    args=parser.parse_args();previous=None
    if args.resume:
        out=args.resume.resolve()
        if out.parent!=(ROOT/'build').resolve() or not out.name.startswith('arm_'):
            raise RuntimeError('Resume must name this workspace build/arm_* directory')
        previous=json.loads((out/'checks.json').read_text())
        if previous['status']!='DEFERRED_MEMORY':raise RuntimeError('Only deferred builds can resume')
        if not all(key in previous for key in ('input_sha256','profile_sha256','compiler_sha256')):
            raise RuntimeError('Deferred before source snapshot; rerun without --resume (no reusable objects)')
        for name,expected in previous['input_sha256'].items():
            if sha(ROOT/name)!=expected:raise RuntimeError('Resume source changed: '+name)
        if sha(PROFILE)!=previous['profile_sha256'] or sha(COMPILER_BIN/(PREFIX+'g++.exe'))!=previous['compiler_sha256']:
            raise RuntimeError('Resume toolchain changed')
        saved=out/('checks_before_resume_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
        saved.write_text(json.dumps(previous,indent=2)+'\n')
    else:
        out = ROOT/'build'/('arm_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
        out.mkdir(parents=True,exist_ok=False)
    report = dict(status='RUNNING',target='ARMv7 Cortex-A9 Linux hard-float NEON',
                  profile=str(PROFILE),output=str(out),checks=[],
                  arm_execution='NOT_RUN',hardware_programmed=False)
    if previous:report['resumed_after']='DEFERRED_MEMORY'
    def run(tool,args,name):
        strings=list(map(str,args));position=len(report['checks'])
        if previous and position<len(previous['checks']):
            old=previous['checks'][position]
            if old['tool']!=tool or old['args']!=strings or old['returncode'] or Path(old['log'])!=out/(name+'.log'):
                raise RuntimeError('Resume command mismatch: '+name)
            if '-o' in strings:
                artifact=Path(strings[strings.index('-o')+1])
                if not artifact.is_file() or not artifact.stat().st_size:raise RuntimeError('Resume object missing: '+str(artifact))
                expected=previous.get('artifact_sha256',{}).get(artifact.name)
                if expected and sha(artifact)!=expected:raise RuntimeError('Resume object changed: '+str(artifact))
                report.setdefault('artifact_sha256',{})[artifact.name]=sha(artifact)
            report['checks'].append(dict(old,reused=True))
            print('REUSE',name,flush=True)
            return Path(old['log']).read_text(errors='replace')
        require_local_memory(name)
        words = [str(PROFILE),PREFIX+tool,*map(str,args)]
        if any(any(c in w for c in '"&|<>^%!\r\n') for w in words):
            raise ValueError('Unsupported batch metacharacter')
        def quote(w):
            return '"'+w+'"' if any(c in w for c in ' /\\') else w
        launcher = out/(name+'.cmd')
        launcher.write_text('@echo off\ncall '+' '.join(map(quote,words))+'\nexit /b %ERRORLEVEL%\n',encoding='ascii')
        log = out/(name+'.log')
        (out/'checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        with log.open('w',encoding='utf-8') as f:
            rc = subprocess.run([r'C:\Windows\System32\cmd.exe','/d','/c',launcher.name],
                                cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
        report['checks'].append(dict(tool=tool,args=list(map(str,args)),returncode=rc,log=str(log)))
        if rc:
            print(log.read_text(errors='replace'),flush=True)
            raise RuntimeError('Failed: '+name)
        if '-o' in strings:
            artifact=Path(strings[strings.index('-o')+1]);report.setdefault('artifact_sha256',{})[artifact.name]=sha(artifact)
        print('PASS',name,flush=True)
        return log.read_text(errors='replace')
    try:
        verify_camera_fixtures()
        jpeg=ensure_jpeg('arm')
        report['jpeg_dependency']=str(jpeg['report'])
        version = run('g++',['--version'],'compiler_version')
        if '7.3.1' not in version or 'Linaro' not in version:
            raise RuntimeError('Requires verified SDK 2018.3 Linaro GCC 7.3.1')
        report['compiler_version'] = version.splitlines()[0]
        for item in json.loads((ROOT/'vendor/orb_engine/provenance.json').read_text(encoding='utf-8-sig')):
            if sha(ROOT/'vendor/orb_engine'/item['Path']) != item['SHA256']:
                raise RuntimeError('Frozen engine changed: '+item['Path'])
        common = ['-pthread','-O2','-g0','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard',
                  '-Wall','-Wextra','-Wno-misleading-indentation',
                  '-I'+str(ROOT/'include'),'-I'+str(ROOT/'interfaces'),'-I'+str(ROOT/'vendor/orb_engine')]
        common+=['-I'+str(jpeg['include'])]
        sources = ['math','pnp','slam','map_store','formats','ui','camera','ports']
        inputs = [ROOT/'src'/(n+'.cpp') for n in sources+['main']]+[ROOT/'tests/test_slam.cpp']
        inputs += sorted((ROOT/'include').rglob('*.hpp'))+sorted((ROOT/'interfaces').glob('*.h'))
        inputs += sorted((ROOT/'vendor/orb_engine').glob('*.c'))+sorted((ROOT/'vendor/orb_engine').glob('*.h'))
        inputs += sorted((ROOT/'vendor/opencv_p3p').glob('*.cpp'))+sorted((ROOT/'vendor/opencv_p3p').glob('*.h'))
        inputs += sorted((ROOT/'tests/fixtures/camera').glob('*'))
        report['input_sha256'] = {str(p.relative_to(ROOT)):sha(p) for p in inputs}
        report['input_sha256'].update(jpeg['inputs'])
        report['input_sha256'][str(jpeg['library'].relative_to(ROOT))]=sha(jpeg['library'])
        if previous and report['input_sha256']!=previous['input_sha256']:
            raise RuntimeError('Resume input set changed')
        report['profile_sha256'] = sha(PROFILE)
        report['compiler_sha256'] = sha(COMPILER_BIN/(PREFIX+'g++.exe'))
        for n in sources+['main','test']:
            source = ROOT/'tests/test_slam.cpp' if n=='test' else ROOT/'src'/(n+'.cpp')
            run('g++',['-std=c++17',*common,'-c',source,'-o',out/(n+'.o')],'compile_'+n)
        run('gcc',['-std=c11',*common,'-c',ROOT/'vendor/orb_engine/engine.c','-o',out/'engine.o'],'compile_engine')
        objects = [out/(n+'.o') for n in sources+['engine']]
        for name,entry in [('zynq-slam','main'),('test-zslam','test')]:
            binary = out/name
            run('g++',[*common,*objects,out/(entry+'.o'),jpeg['library'],'-static-libstdc++','-static-libgcc',
                       '-lstdc++fs','-o',binary],'link_'+name)
            elf = run('readelf',['-h','-A','-l','-d','-V',binary],'elf_'+name)
            for required in ['ELF32','ARM','hard-float ABI','/lib/ld-linux-armhf.so.3','Tag_Advanced_SIMD_arch: NEONv1']:
                if required not in elf:
                    raise RuntimeError('Unexpected ARM ELF ABI: '+required)
            if 'Shared library: [libstdc++' in elf or 'Shared library: [libgcc_s' in elf:
                raise RuntimeError('C++/GCC runtime unexpectedly dynamic')
            report.setdefault('binaries',{})[name] = dict(bytes=binary.stat().st_size,sha256=sha(binary),
                needed=re.findall(r'Shared library: \[([^\]]+)\]',elf),
                glibc_versions=sorted(set(re.findall(r'GLIBC_[0-9.]+',elf))))
        import shutil
        shutil.copytree(ROOT/'tests/fixtures/camera',out/'test-fixtures/camera',dirs_exist_ok=True)
        report['status'] = 'PASS'
    except ResourceDeferred as error:
        report.update(status='DEFERRED_MEMORY',error=str(error))
        print(str(error),flush=True)
        return 75
    except Exception as error:
        report.update(status='FAIL',error=str(error))
        raise
    finally:
        (out/'checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('PASS ARM cross-build; execution NOT_RUN:',out,flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
