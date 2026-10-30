"""Portable Cortex-A9 Linux build with explicit SDK-compatible compiler and provenance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
ZYNQ=ROOT/'zynq7015_demo'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--compiler',type=Path,default=os.environ.get('FPGA_ZYNQ_CXX'))
    p.add_argument('--jpeg-library',type=Path,default=os.environ.get('FPGA_ZYNQ_TURBOJPEG_LIBRARY'))
    p.add_argument('--output',type=Path,default=ROOT/'orb60/build/demo_bridge/arm')
    p.add_argument('--fully-static',action='store_true',help='Separate ARM Linux candidate: bundle libc/libstdc++, validate no loader/shared dependencies')
    p.add_argument('--with-selftests',action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',scope='ARM cross-build only; no ARM execution or board acceptance',commands=[])
    try:
        if not a.compiler or not a.compiler.is_file():
            report.update(status='BLOCKED_TOOLCHAIN',error='Configure FPGA_ZYNQ_CXX or --compiler with SDK-compatible ARM Linux hard-float GCC7.3.1; profile .cmd files are not compilers')
            return 78
        compiler=a.compiler.resolve();gcc=compiler.with_name(compiler.name.replace('g++','gcc'))
        version=subprocess.check_output([compiler,'--version']).decode(errors='replace')
        target=subprocess.check_output([compiler,'-dumpmachine']).decode().strip()
        if target!='arm-linux-gnueabihf' or ('7.3.1' not in version and not a.fully_static):
            raise ValueError('Expected recorded GCC7.3.1 ARM Linux hard-float toolchain')
        if not a.jpeg_library:
            a.jpeg_library=ROOT/'zynq7015_usb_slam_20261024/source/build/jpeg_arm_b1b33a5bb6b5c785/libturbojpeg.a'
            if not a.jpeg_library.is_file():a.jpeg_library=Path(__file__).parent/'dependencies/libturbojpeg-arm.a'
        if not a.jpeg_library.is_file():
            raise ValueError('Provide the pinned ARM NEON libturbojpeg3.2.0 static library')
        expected=json.loads((Path(__file__).parent/'dependencies/provenance.json').read_text())['libturbojpeg-arm.a']['sha256']
        if hashlib.sha256(a.jpeg_library.read_bytes()).hexdigest()!=expected:
            raise ValueError('ARM JPEG static library differs from retained dependency')
        if os.name=='nt':
            sys.path.insert(0,str(ZYNQ/'scripts'))
            from resource_guard import require_local_memory
        else:
            def require_local_memory(operation):
                info={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')}
                available=info['MemAvailable']/1024
                if available<1536:raise RuntimeError('DEFERRED_MEMORY '+operation)
                return available
        env=os.environ.copy();env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
        flags=['-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-O2','-g0','-pthread',
               '-I'+str(ZYNQ/'include'),'-I'+str(ZYNQ/'interfaces'),'-I'+str(ZYNQ/'vendor/orb_engine'),
               '-I'+str(ZYNQ/'vendor/jpeg_turbo/upstream/src')]
        sources=[ZYNQ/'src'/(n+'.cpp') for n in ('math','pnp','slam','map_store','formats','ui','camera','ports','demo_main')]
        sources.append(ZYNQ/'vendor/orb_engine/engine.c');objects=[]
        def run(args,name):
            available=require_local_memory(name)
            with (a.output/(name+'.log')).open('w') as f:
                rc=subprocess.run(list(map(str,args)),env=env,stdout=f,stderr=subprocess.STDOUT,timeout=300).returncode
            report['commands'].append(dict(name=name,returncode=rc,available_mib=available))
            if rc:raise RuntimeError('Cross-build failed: '+name)
            print('PASS',name,flush=True)
        for source in sources:
            obj=a.output/(source.stem+'.o');objects.append(obj)
            run([gcc if source.suffix=='.c' else compiler,'-std=c11' if source.suffix=='.c' else '-std=c++17',*flags,'-c',source,'-o',obj],'compile_'+source.stem)
        binary=a.output/'zynq-demo'
        # libstdc++ uses weak gthread references. On the separate glibc2.31
        # static ARM candidate, ordinary -pthread can select libc stubs.
        # The board thread/condition probe verifies whole-archive pthread.
        static_flags=['-static','-Wl,--whole-archive','-lpthread','-Wl,--no-whole-archive'] if a.fully_static else []
        run([compiler,*flags,*objects,a.jpeg_library,*static_flags,'-static-libstdc++','-static-libgcc','-lstdc++fs','-o',binary],'link')
        installer_object=a.output/'map_install.o'
        run([compiler,'-std=c++17',*flags,'-c',Path(__file__).parent/'map_install.cpp','-o',installer_object],'compile_map_installer')
        run([compiler,*flags,*[obj for obj in objects if obj.name!='demo_main.o'],installer_object,a.jpeg_library,*static_flags,
             '-static-libstdc++','-static-libgcc','-lstdc++fs','-o',a.output/'zynq-map-install'],'link_map_installer')
        data=binary.read_bytes()
        if data[:5]!=b'\x7fELF\x01' or int.from_bytes(data[18:20],'little')!=40:
            raise ValueError('Not an ELF32 ARM application')
        if a.fully_static:
            import struct
            phoff=struct.unpack_from('<I',data,28)[0];entsize,count=struct.unpack_from('<HH',data,42)
            if any(struct.unpack_from('<I',data,phoff+i*entsize)[0] in (2,3) for i in range(count)):
                raise ValueError('Static candidate unexpectedly has PT_INTERP/PT_DYNAMIC')
            if not struct.unpack_from('<I',data,36)[0]&0x400:raise ValueError('ARM hard-float ABI flag missing')
        if a.with_selftests:
            common=[obj for obj in objects if obj.name!='demo_main.o']
            for name,source in [('test-zslam',ZYNQ/'tests/test_slam.cpp'),('test-bridge',Path(__file__).parent/'tests/test_bridge.cpp')]:
                obj=a.output/(name+'.o')
                run([compiler,'-std=c++17',*flags,'-c',source,'-o',obj],'compile_'+name)
                run([compiler,*flags,*common,obj,a.jpeg_library,*static_flags,'-static-libstdc++','-static-libgcc','-lstdc++fs','-o',a.output/name],'link_'+name)
            helper=ZYNQ/'tools/s1_reset_bridge.c'
            run([gcc,'-std=c11',*flags,helper,*static_flags,'-o',a.output/'s1-reset-bridge'],'build_s1_helper')
        report.update(status='PASS',compiler=version.splitlines()[0],target=target,fully_static=a.fully_static,pthread_whole_archive=a.fully_static,
                      compiler_sha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),
                      jpeg_sha256=hashlib.sha256(a.jpeg_library.read_bytes()).hexdigest(),
                      binary_sha256=hashlib.sha256(data).hexdigest(),
                      required_glibc=sorted({v.decode() for v in re.findall(rb'GLIBC_[0-9.]+',data)}),
                      board_abi_execution='NOT_VERIFIED')
        return 0
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));raise
    finally:
        (a.output/'checks.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':raise SystemExit(main())
