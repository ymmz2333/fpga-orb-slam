"""Validate native build products; never treats a stale progress file as success."""
import argparse,hashlib,json,platform,re,subprocess
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path);p.add_argument('--run',default='ps_native_v2_verified_20261102')
    a=p.parse_args();root=a.root.resolve();run=root/'runs'/a.run;run.mkdir(parents=True,exist_ok=False)
    if platform.machine()!='aarch64':raise RuntimeError('Native AArch64 verification required')
    build=root/'build';source=root/'slam';binary=build/'bin/mono_kv260';library=build/'lib/libORB_SLAM3.so'
    original=root/'runs/ps_native_v2_20261102_restart/console.log'
    log=original.read_text(errors='replace')
    if '[100%] Built target mono_kv260' not in log:raise RuntimeError('Missing completed native build evidence')
    architecture=subprocess.check_output(['file',str(binary),str(library)],text=True)
    dependencies=subprocess.check_output(['ldd',str(binary)],text=True)
    lines=architecture.splitlines()
    if len(lines)!=2 or any(not re.search(r'ELF 64-bit .*ARM aarch64',line) for line in lines) or 'not found' in dependencies:
        raise RuntimeError('Native architecture/dependency check failed')
    # The old marker had a Python-3.11-only hashing API; retain its failure and
    # validate the actual completed build/products in a separate evidence run.
    files=[binary,library,source/'CMakeLists.txt',source/'src/System.cc',source/'src/Map.cc',source/'Examples/Monocular/mono_kv260.cc',original]
    record={'status':'SUCCEEDED','exit_code':0,'scope':'native build/link product verification; mapping replay is a separate gate',
            'optimization':'Release -O2 throughout','source':str(source),'build':str(build),
            'original_run':'ps_native_v2_20261102_restart','original_recording_error':'hashlib.file_digest unavailable on Python3.10; original console/trace retained',
            'sha256':{str(f):sha(f) for f in files}}
    (run/'architecture.txt').write_text(architecture)
    (run/'dependencies.txt').write_text(dependencies)
    (run/'state.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record),flush=True)


if __name__=='__main__':main()
