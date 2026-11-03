"""Read-only KV260 checks. Does not load firmware or alter system settings."""
import argparse
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import re
import shutil
from .common import digest,save


def query_current_device(driver='xrt'):
    if driver not in ('xrt','vivado'):raise RuntimeError('Explicit xrt or vivado DPU driver required')
    env={**os.environ,'XLNX_DISABLE_LOAD_XCLBIN':'1'}
    if driver=='vivado':
        import array,fcntl
        fd=os.open('/dev/dpu',os.O_RDWR|os.O_CLOEXEC)
        try:
            fingerprint=array.array('Q',[0]);info=array.array('I',[0])
            # Official linux-xlnx DPU ioctl ABI: _IOR('D',5,u64), _IOR('D',4,u32).
            fcntl.ioctl(fd,0x80084405,fingerprint,True);fcntl.ioctl(fd,0x80044404,info,True)
        finally:os.close(fd)
        import tools_extra_ops
        libraries=['libvart-runner.so','libxir.so']
        versions=tools_extra_ops.xilinx_version(libraries)
        query={'driver':'vivado_ioctl','register_info':hex(info[0]),'kernels':[{'fingerprint':hex(fingerprint[0])}],
               'VAI Version':dict(zip(libraries,versions))}
    else:
        try:
            result=subprocess.run([sys.executable,'-m','xdputil','query'],capture_output=True,text=True,timeout=30,check=True,env=env)
        except subprocess.CalledProcessError as error:
            detail=(error.stderr or error.stdout or '')[-1600:].strip()
            raise RuntimeError(f'Read-only DPU query failed (exit {error.returncode}): {detail}') from error
        query=json.loads(result.stdout)
    # Native VAI 2.5 xdputil omits XRT from its JSON. Read the installed XRT
    # utility's explicit version rather than substituting a configured value.
    tool=shutil.which('xbutil')
    if not tool:raise RuntimeError('Read-only native xbutil version probe is required')
    native=subprocess.run([tool,'--version'],capture_output=True,text=True,timeout=10,check=True,env=env)
    query['XRT Runtime Probe']={'version':parse_xrt_version(native.stdout),'tool':tool,'tool_sha256':digest(tool)}
    return query


def parse_xrt_version(text):
    values=re.findall(r'^Version\s*:\s*(\d+\.\d+\.\d+)\s*$',text,re.MULTILINE)
    if len(values)!=1:raise RuntimeError('Missing/ambiguous native XRT Version line')
    return values[0]


def fingerprints(value):
    found=set()
    if isinstance(value,dict):
        for k,v in value.items():
            if 'fingerprint' in str(k).lower():
                try:found.add(hex(int(v,0) if isinstance(v,str) else int(v)))
                except (TypeError,ValueError):pass
            found.update(fingerprints(v))
    elif isinstance(value,list):
        for v in value:found.update(fingerprints(v))
    return found

def validate(os_release,machine,query,arch,runtime):
    if machine!='aarch64':raise RuntimeError('Real KV260 requires aarch64; host reference is separate')
    if os_release.get('ID')!='ubuntu' or os_release.get('VERSION_ID')!='22.04':raise RuntimeError('Expected Ubuntu 22.04')
    expected=fingerprints(arch);actual=fingerprints(query)
    if not expected or not expected.issubset(actual):raise RuntimeError('DPU fingerprint mismatch/missing')
    if not re.search(r'(?:^|so\.|\bVersion:\s*)2\.5(?:[.\s-]|$)',runtime):raise RuntimeError('Expected VART/Vitis AI 2.5 runtime')
    return sorted(expected)


def check_xrt(query,expected):
    if not expected or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?',expected):raise RuntimeError('An explicit XRT version prefix from the matched board platform is required')
    found=[]
    def visit(v,context=False):
        if isinstance(v,dict):
            for key,value in v.items():
                matched=context or 'xrt' in key.lower()
                if matched and isinstance(value,str):found.extend(re.findall(r'\b\d+\.\d+(?:\.\d+)?\b',value))
                visit(value,matched)
        elif isinstance(v,list):
            for value in v:visit(value,context)
    visit(query)
    if not found or not any(v==expected or v.startswith(expected+'.') for v in found):raise RuntimeError('XRT version missing or mismatched: '+str(found))
    return found

def main():
    p=argparse.ArgumentParser();p.add_argument('--arch',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expected-xrt-prefix',required=True,help='From the matched board platform build/release, never inferred from host Docker')
    p.add_argument('--profile',type=Path,help='Defaults to target_profile.json next to arch.json')
    p.add_argument('--driver',choices=['xrt','vivado'],default='xrt',help='Explicit hardware control ABI, never an automatic fallback')
    a=p.parse_args()
    record={'status':'PREFLIGHT_FAILED','hardware_inference_verified':False,
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip() if Path('/proc/sys/kernel/random/boot_id').is_file() else None}
    try:
        os.environ['XLNX_DISABLE_LOAD_XCLBIN']='1'
        if a.driver=='vivado':os.environ['DISABLE_DPU_CONTROLLER_XRT']='1'
        release=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        release={k:v.strip('"') for k,v in release.items()}
        query=query_current_device(a.driver);arch=json.loads(a.arch.read_text())
        profile_path=a.profile or a.arch.with_name('target_profile.json')
        profile=json.loads(profile_path.read_text())
        if profile.get('arch_sha256')!=digest(a.arch):raise ValueError('Target profile/arch hash mismatch')
        if not fingerprints(arch):arch={**arch,'compiled_fingerprints':[{'fingerprint':f} for f in profile.get('fingerprints',[])]}
        import xir,vart
        from vitis_ai_library import GraphRunner
        import cv2,numpy,scipy
        versions={name:getattr(module,'__version__','') for name,module in [('xir',xir),('vart',vart)]}
        # xdputil version text is retained; require an explicit runtime version in its query.
        def runtime_versions(v):
            if isinstance(v,dict):
                for k,x in v.items():
                    if 'vart' in k.lower() and isinstance(x,str):yield x
                    yield from runtime_versions(x)
            elif isinstance(v,list):
                for x in v:yield from runtime_versions(x)
        runtime=versions['vart'] or next(iter(runtime_versions(query)),'')
        expected=validate(release,platform.machine(),query,arch,runtime)
        xrt=check_xrt(query,a.expected_xrt_prefix)
        record.update(status='PROFILE_MATCH',arch_sha256=digest(a.arch),fingerprints=expected,
                      runtime=runtime,versions=versions,query=query,os=release,machine=platform.machine(),
                      xrt=xrt,expected_xrt_prefix=a.expected_xrt_prefix)
        record['driver']=a.driver
    except Exception as e:record['error']=str(e)
    save(a.output,record);print(record['status'])
    if record['status']!='PROFILE_MATCH':raise SystemExit(1)

if __name__=='__main__':main()
