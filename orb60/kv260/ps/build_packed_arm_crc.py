"""PS-only native input/CRC candidate; preserve all geometry and PL results."""
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


def protocol_transform(source):
    old='static inline uint32_t orb_crc32(const void *p, size_t n) {'
    new=old.replace('orb_crc32(','orb_crc32_software(')
    if source.count(old)!=1 or not source.endswith('#endif\n'):
        raise ValueError('Unreviewed retained CRC boundary')
    prefix='#include <sys/auxv.h>\n#include <asm/hwcap.h>\n'
    wrapper='''extern "C" uint32_t orb_crc32_arm(const void*, size_t);
static inline uint32_t orb_crc32(const void* p, size_t n) {
    static const bool hardware=(getauxval(AT_HWCAP)&HWCAP_CRC32)!=0;
    return hardware?orb_crc32_arm(p,n):orb_crc32_software(p,n);
}
'''
    changed=prefix+source.replace(old,new).removesuffix('#endif\n')+wrapper+'#endif\n'
    recovered=changed.removeprefix(prefix).replace(wrapper,'').replace(new,old)
    if recovered!=source:raise ValueError('Retained CRC or protocol math changed')
    return changed


def packed_transform(source):
    old='for(size_t i=0;i<gray.total();++i)'
    new='const size_t pixels=gray.total();for(size_t i=0;i<pixels;++i)'
    if source.count(old)!=1:raise ValueError('Unreviewed packed luma loop')
    changed=source.replace(old,new)
    if changed.replace(new,old)!=source:raise ValueError('Packed pixels changed')
    return changed


def run(root,adapter,base,library_base,fixture,output):
    root,adapter,base,library_base,fixture,output=map(lambda p:Path(p).resolve(),(root,adapter,base,library_base,fixture,output))
    if platform.machine()!='aarch64' or available()<1536*1024:raise ValueError('Native KV260 with compile memory margin required')
    old=json.loads((base/'BUILD.json').read_text());flags=json.loads((adapter/'BUILD.json').read_text());library=json.loads((library_base/'BUILD.json').read_text())
    if old['status']!='NATIVE_PACKED_STREAM_COMPONENT_PASS' or flags['status']!='NATIVE_NETWORK_ADAPTER_BUILD_PASS' or library['status']!='NATIVE_EXACT_HOTSPOTS_COMPONENT_PASS':raise ValueError('Explicit frozen base products required')
    protocol=root/'slam/include/Orb60Protocol.h'
    liblink=list(library['link_commands']['library']);mainlink=list(old['link_commands']['executable'])
    feature_slots=[i for i,x in enumerate(liblink) if x.endswith('/FeatureIO.o')]
    main_slots=[i for i,x in enumerate(mainlink) if x.endswith('/network.o')]
    lib_slots=[i for i,x in enumerate(mainlink) if x.endswith('/libORB_SLAM3.so')]
    if len(feature_slots)!=1 or len(main_slots)!=1 or len(lib_slots)!=1:raise ValueError('Unreviewed main/feature/library link')
    if mainlink[lib_slots[0]]!=str(library_base/'lib/libORB_SLAM3.so'):raise ValueError('Stream candidate uses another math library')
    feature_base=Path(liblink[feature_slots[0]]).parent
    before={**old['products_sha256'],**flags['products_sha256'],**library['products_sha256'],str(protocol):digest(protocol)}
    for cmd in (liblink,mainlink):
        for value in cmd:
            if value.endswith('.o'):
                path=Path(value);path=path if path.is_absolute() else root/'build'/path
                before[str(path)]=digest(path)
    for folder in (base/'source',feature_base/'source'):
        for p in folder.iterdir():
            if p.is_file():before[str(p)]=digest(p)
    if any(digest(p)!=h for p,h in before.items()):raise ValueError('Frozen base modified')
    f=json.loads((fixture/'FIXTURE.json').read_text())
    if f['status']!='INDEPENDENT_IEEE_CRC_FIXTURE' or any(digest(fixture/n)!=h for n,h in f['files_sha256'].items()):raise ValueError('Independent CRC fixture mismatch')
    output.mkdir(parents=True,exist_ok=False)
    for n in ('source','lib','bin'):(output/n).mkdir()
    for p in (base/'source').iterdir():
        if p.is_file():(output/'source'/p.name).write_bytes(p.read_bytes())
    for n in ('FeatureIO.cc','FpgaPipeline.h'):(output/'source'/n).write_bytes((feature_base/'source'/n).read_bytes())
    (output/'source/Orb60Protocol.h').write_text(protocol_transform(protocol.read_text()))
    packed=output/'source/PackedYuvSource.h';packed.write_text(packed_transform(packed.read_text()))
    authored=Path(__file__).parent
    for n in ('Crc32Arm.cc','check_crc_arm.cc'):(output/'source'/n).write_bytes((authored/n).read_bytes())
    common=list(flags['commands'][0]);common=common[:common.index('-c')]
    common=[common[0],'-I'+str(output/'source'),'-include',str(output/'source/Orb60Protocol.h'),*common[1:]]
    crc=output/'Crc32Arm.o';main=output/'network.o';feature=output/'FeatureIO.o';check=output/'crc_check.o'
    lib=output/'lib/libORB_SLAM3.so';exe=output/'bin/mono_kv260_network';unit=output/'bin/check_crc_arm'
    liblink[feature_slots[0]]=str(feature);liblink.insert(feature_slots[0],str(crc));liblink[liblink.index('-o')+1]=str(lib)
    mainlink[main_slots[0]]=str(main);mainlink[lib_slots[0]]=str(lib);mainlink[mainlink.index('-o')+1]=str(exe)
    for i,x in enumerate(mainlink):
        if x.startswith('-Wl,-rpath,'):mainlink[i]='-Wl,-rpath,'+str(lib.parent)+':'+x.removeprefix('-Wl,-rpath,')
    commands=[];state=dict(status='RUNNING',scope='PS IEEE CRC instruction dispatch plus invariant luma loop bound only; all retained geometry objects unchanged, component status is not system acceptance',protected_sha256=before,fixture=f,commands=commands,source_sha256={p.name:digest(p) for p in (output/'source').iterdir()},link_commands=dict(library=liblink,executable=mainlink))
    def invoke(command):
        commands.append(command);child=subprocess.Popen(command,cwd=root/'build',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while child.poll() is None:
                if available()<256*1024:
                    os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);raise MemoryError('Own compile stopped below256MiB available')
                time.sleep(.25)
            if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        finally:
            if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
    try:
        with (output/'build.log').open('w') as log:
            invoke([*common,'-march=armv8-a+crc','-c',str(output/'source/Crc32Arm.cc'),'-o',str(crc)])
            invoke([*common,'-c',str(output/'source/check_crc_arm.cc'),'-o',str(check)])
            invoke([common[0],str(check),str(crc),'-o',str(unit)])
            state['crc_unit']=json.loads(subprocess.check_output([str(unit),str(fixture/'vectors.bin'),str(fixture/'expected.csv')],text=True))
            if state['crc_unit']['status']!='EXACT_ARM_IEEE_CRC_PASS' or state['crc_unit']['cases']!=f['cases']:raise ValueError('Independent native CRC gate failed')
            assembly=subprocess.check_output(['objdump','-d',str(crc)],text=True)
            if 'crc32x' not in assembly or 'crc32cx' in assembly:raise ValueError('Wrong checksum instruction')
            (output/'crc_assembly.txt').write_text(assembly)
            for src,obj in [('FeatureIO.cc',feature),('mono_kv260_network.cc',main)]:invoke([*common,'-c',str(output/'source'/src),'-o',str(obj)])
            invoke(liblink);invoke(mainlink)
        deps=subprocess.check_output(['ldd','-r',str(exe)],text=True,stderr=subprocess.STDOUT)
        if 'not found' in deps or 'undefined symbol' in deps or str(lib) not in deps:raise ValueError('Private native dependency mismatch')
        if any(digest(p)!=h for p,h in before.items()):raise ValueError('Frozen base changed')
        state.update(status='NATIVE_PACKED_ARM_CRC_COMPONENT_PASS',dependencies=deps,products_sha256={str(p):digest(p) for p in (lib,exe,unit)})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'BUILD.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],crc_unit=state['crc_unit'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('root','adapter','base','library_base','fixture','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    run(**vars(p.parse_args()))
