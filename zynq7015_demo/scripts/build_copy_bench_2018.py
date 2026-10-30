"""Small ARM-only WC benchmark build; never loads PL or changes SD selection."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
from resource_guard import require_local_memory,ResourceDeferred
root=Path(__file__).resolve().parents[1]
profile=Path('C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/zynq-arm-linux-2018.3.cmd')
out=root/'build'/('copy_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report=dict(status='RUNNING',profile=str(profile),checks=[],hardware='NOT_RUN')
def run(tool,args,name):
    require_local_memory(name)
    words=[str(profile),'arm-linux-gnueabihf-'+tool,*map(str,args)]
    if any(any(c in w for c in '\"&|<>^%!\r\n') for w in words):raise ValueError('Unsupported batch metacharacter')
    quote=lambda w:'"'+w+'"' if any(c in w for c in ' /\\') else w
    launcher=out/(name+'.cmd');launcher.write_text('@echo off\ncall '+' '.join(map(quote,words))+'\nexit /b %ERRORLEVEL%\n',encoding='ascii')
    log=out/(name+'.log')
    with log.open('w') as f:rc=subprocess.run([r'C:\Windows\System32\cmd.exe','/d','/c',launcher.name],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=90).returncode
    report['checks'].append(dict(name=name,returncode=rc,log=str(log)))
    if rc:raise RuntimeError(log.read_text(errors='replace'))
    print('PASS',name,flush=True)
try:
    for entry in json.loads((root/'vendor/orb_engine/provenance.json').read_text(encoding='utf-8-sig')):
        assert digest(root/'vendor/orb_engine'/entry['Path'])==entry['SHA256']
    inputs=[root/'tools/bench_wc_copy.cpp',root/'vendor/orb_engine/engine.c',root/'vendor/orb_engine/engine.h',root/'vendor/orb_engine/orb60_registers.h',root/'vendor/orb_engine/protocol.h']
    report['input_sha256']={p.relative_to(root).as_posix():digest(p) for p in inputs}
    flags=['-O2','-g0','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-Wall','-Wextra','-I'+str(root/'vendor/orb_engine')]
    run('gcc',['-std=c11',*flags,'-c',inputs[1],'-o',out/'engine.o'],'compile_engine')
    run('g++',['-std=c++17',*flags,inputs[0],out/'engine.o','-static-libstdc++','-static-libgcc','-o',out/'bench-wc-copy'],'compile_link_copy')
    run('readelf',['-h','-A','-l','-d','-V',out/'bench-wc-copy'],'elf_copy')
    report.update(status='PASS',binary=str(out/'bench-wc-copy'),sha256=digest(out/'bench-wc-copy'))
except ResourceDeferred as e:report.update(status='DEFERRED_MEMORY',error=str(e));print(str(e));sys.exit(75)
except Exception as e:report.update(status='FAIL',error=str(e));raise
finally:(out/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(status=report['status'],output=str(out),sha256=report.get('sha256')),indent=2),flush=True)
