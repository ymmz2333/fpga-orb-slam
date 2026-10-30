"""Build a host libfdt utility with SDK sources, without Linux/WSL or global PATH."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

root=Path(__file__).resolve().parents[1]
sdk=Path('C:/Xilinx/SDK/2018.3/data/embeddedsw/lib/sw_apps/atf_sources/src')
sources=sorted((sdk/'lib/libfdt').glob('*.c'))+[root/'tools/prepare_device_tree.c']
out=root/'build/dt_tool';out.mkdir(parents=True,exist_ok=True)
compiler=Path('C:/Users/dmsun/mingw/mingw64/bin/gcc.exe')
env=dict(os.environ);env['PATH']=str(compiler.parent)+';'+env.get('SystemRoot','C:/Windows')+'/System32'
command=[compiler,'-std=c11','-O2','-Wall','-I'+str(sdk/'include/lib/libfdt'),'-I'+str(sdk/'lib/libfdt'),*sources,'-o',out/'prepare-dtb.exe']
with (out/'compile.log').open('w') as log:
    rc=subprocess.run(list(map(str,command)),env=env,stdout=log,stderr=subprocess.STDOUT).returncode
report=dict(status='PASS' if rc==0 else 'FAIL',command=list(map(str,command)),
            input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            library='Unmodified SDK 2018.3 libfdt, BSD licensing option; notice in libfdt_env.h')
(out/'checks.json').write_text(json.dumps(report,indent=2))
print(report['status'],out)
if rc:print((out/'compile.log').read_text(errors='replace'))
raise SystemExit(rc)
