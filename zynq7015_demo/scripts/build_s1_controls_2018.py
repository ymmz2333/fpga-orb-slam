"""Build independent ARM S1/FIFO and capture-affinity helpers; no PL changes."""
from pathlib import Path
import datetime,hashlib,json,os,subprocess
from resource_guard import require_local_memory,ResourceDeferred
root=Path(__file__).resolve().parents[1]
profile=Path('C:/Users/dmsun/Documents/Codex/toolchains/fpga/bin/zynq-arm-linux-2018.3.cmd')
sdk=Path('C:/Xilinx/SDK/2018.3/gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin')
out=root/'build'/('s1_controls_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
checks=[];report=dict(status='RUNNING',scope='ARM helper build/ABI only; evdev and reset operation require board verification')
def run(tool,args,label):
    require_local_memory(label)
    command='call "'+str(profile)+'" '+tool+' '+subprocess.list2cmdline([str(a) for a in args])
    batch=out/(label+'.cmd');batch.write_text('@echo off\n'+command+'\nexit /b %ERRORLEVEL%\n',encoding='ascii')
    result=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',batch.name],cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log=out/(label+'.log');log.write_bytes(result.stdout);checks.append(dict(label=label,exit_code=result.returncode,log=str(log),command=command))
    if result.returncode:raise RuntimeError(label+' failed: '+str(log))
    return result.stdout.decode(errors='replace')
try:
    flags=['-std=gnu99','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-static-libgcc']
    for source,binary in [('s1_reset_bridge.c','s1-reset-bridge'),('capture_affinity.c','capture-affinity')]:
        run('arm-linux-gnueabihf-gcc',[*flags,root/'tools'/source,'-o',out/binary],'compile_'+binary)
        elf=run('arm-linux-gnueabihf-readelf',['-h','-A','-l',out/binary],'elf_'+binary)
        for token in ['ELF32','ARM','hard-float ABI','/lib/ld-linux-armhf.so.3','VFP registers']:assert token in elf,token
    report.update(status='PASS',sources={s:sha(root/'tools'/s) for s in ['s1_reset_bridge.c','capture_affinity.c']},binaries={s:sha(out/s) for s in ['s1-reset-bridge','capture-affinity']},compiler_sha256=sha(sdk/'arm-linux-gnueabihf-gcc.exe'))
except ResourceDeferred as e:report.update(status='DEFERRED_MEMORY',error=str(e));raise SystemExit(75)
except Exception as e:report.update(status='FAIL',error=str(e));raise
finally:
    report['checks']=checks;(out/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(build=str(out),status=report['status']),indent=2),flush=True)
