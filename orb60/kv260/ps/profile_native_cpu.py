"""Attach CPU sampling to an owned, explicitly diagnostic actual-DPU run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import time


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def elf_layout(path):
    with Path(path).open('rb') as f:
        header=f.read(64)
        if header[:6]!=b'\x7fELF\x02\x01':raise ValueError('Expected little-endian ELF64')
        fields=struct.unpack('<16sHHIQQQIHHHHHH',header)
        kind,phoff,entsize,count=fields[1],fields[5],fields[9],fields[10]
        if fields[2]!=183 or kind not in (2,3) or entsize!=56 or count>256:raise ValueError('Unreviewed ELF layout')
        f.seek(phoff);segments=[]
        for _ in range(count):
            p=struct.unpack('<IIQQQQQQ',f.read(56))
            if p[0]==1:segments.append(dict(offset=p[2],vaddr=p[3],filesz=p[5],memsz=p[6],flags=p[1]))
        return dict(type=kind,segments=segments)


def capture_symbols(out):
    paths=set()
    for line in (out/'maps.txt').read_text().splitlines():
        parts=line.split(None,5)
        if len(parts)==6 and 'x' in parts[1] and parts[5].startswith('/'):
            paths.add(parts[5])
    folder=out/'symbols';folder.mkdir()
    index={}
    for name in sorted(paths):
        p=Path(name)
        if not p.is_file():raise ValueError('Mapped ELF no longer available: '+name)
        key=hashlib.sha256(name.encode()).hexdigest()[:16]
        item=dict(sha256=digest(p),layout=elf_layout(p),symbol_files=[])
        for mode,flags in [('static',[]),('dynamic',['-D'])]:
            command=['nm',*flags,'-n','-S','-C','--defined-only',name]
            r=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if r.returncode:raise ValueError('Cannot read mapped symbols: '+r.stderr[-300:])
            dest=folder/(key+'_'+mode+'.nm');dest.write_text(r.stdout);item['symbol_files'].append(str(dest.relative_to(out)))
        index[name]=item
    (out/'ELF_INDEX.json').write_text(json.dumps(index,indent=2)+'\n')


def run(control,run_dir,output,sampler,expected_executable,max_seconds):
    control,run_dir,output,sampler,expected_executable=map(lambda p:Path(p).resolve(),(control,run_dir,output,sampler,expected_executable))
    if platform.machine()!='aarch64' or max_seconds<1 or max_seconds>600:raise ValueError('Native bounded CPU diagnostic required')
    output.mkdir(parents=True,exist_ok=False)
    state=dict(status='WAITING',scope='CPU samples from initial native tasks only. No hardware or throughput acceptance.',
               control=str(control),run=str(run_dir),sampler_sha256=digest(sampler),executable_sha256=digest(expected_executable),
               source_sha256=digest(Path(__file__)))
    def save():(output/'PROFILE.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        deadline=time.monotonic()+180
        while True:
            report=json.loads((control/'RESULT.json').read_text()) if (control/'RESULT.json').is_file() else None
            if report and not report['profiling']:raise ValueError('Refusing to sample a performance acceptance run')
            if report and report['status']!='RUNNING':raise ValueError('Owned run already ended before sampling')
            if report and (run_dir/'processing_started.json').is_file():break
            if time.monotonic()>deadline:raise TimeoutError('Owned native processing did not start')
            time.sleep(.1)
        pid=report['pids']['native']
        if type(pid) is not int or pid<=1 or Path(os.readlink('/proc/%d/exe'%pid)).resolve()!=expected_executable:
            raise ValueError('Owned native process identity mismatch')
        if report.get('depth')!='actual_KV260_DPU':raise ValueError('Explicit actual-DPU pipeline required')
        state.update(status='SAMPLING',pid=pid,target_stat_before=Path('/proc/%d/stat'%pid).read_text(),
                     declared_depth=report['depth'],native_products=report.get('native_products'))
        save()
        with (output/'sampler.log').open('w') as log:
            subprocess.run([str(sampler),str(pid),str(output),str(max_seconds)],stdout=log,stderr=subprocess.STDOUT,check=True)
        evidence=json.loads((output/'SAMPLER.json').read_text())
        if evidence['status']!='NATIVE_CPU_SAMPLES_RECORDED' or evidence['lost'] or evidence['samples']<100:
            raise ValueError('Insufficient complete CPU samples')
        capture_symbols(output)
        deadline=time.monotonic()+180
        while True:
            final=json.loads((control/'RESULT.json').read_text())
            if final['status']!='RUNNING':break
            if time.monotonic()>deadline:raise TimeoutError('Owned DPU pipeline did not finalize')
            time.sleep(.25)
        if not final.get('hardware_inference_verified') or not final.get('frame_checks') or final['frame_checks']['cpu_orb_calls']:
            raise ValueError('CPU samples exist but real-DPU pipeline was not verified')
        state.update(status='CPU_DIAGNOSTIC_CAPTURED',sampling=evidence,actual_dpu_pipeline_verified=True,
                     pipeline_status=final['status'],pipeline_report_sha256=digest(control/'RESULT.json'))
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:save()
    print(json.dumps(dict(status=state['status'],samples=state['sampling']['samples'],pid=state['pid'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('control','run-dir','output','sampler','expected-executable'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--max-seconds',type=int,default=120)
    run(**vars(p.parse_args()))
