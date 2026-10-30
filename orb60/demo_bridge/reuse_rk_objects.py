"""Bounded native build-cache reuse after source/flags/nonvirtual-header checks.

Only the isolated build is written. Original objects are copied, never linked
back to mutable outputs. The running make schedulers pause during the copy;
the active compiler's output and all changed translation units are excluded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--retained',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--build',type=Path,required=True)
    a=p.parse_args();old,new,build=[x.resolve() for x in (a.retained,a.source,a.build)]
    if old==new or old in build.parents or old in new.parents:raise ValueError('Isolated source/build required')
    ob=old/'build/CMakeFiles/ORB_SLAM3.dir';nb=build/'CMakeFiles/ORB_SLAM3.dir'
    def flags(path):return {l.split('=',1)[0].strip():l.split('=',1)[1].strip() for l in path.read_text().splitlines() if l.startswith(('CXX_FLAGS =','CXX_DEFINES =','CXX_INCLUDES ='))}
    of=flags(ob/'flags.make');nf=flags(nb/'flags.make')
    if {k:v.replace(str(old),str(new)) for k,v in of.items()}!=nf:raise ValueError('Compile flags/defines/include roots differ')
    original=(old/'include/System.h').read_text();updated=(new/'include/System.h').read_text()
    if updated.replace('\n    void ExportBridgeMap(const string &directory);','')!=original:raise ValueError('System.h change is not solely the nonvirtual method declaration')
    for header in (old/'include').rglob('*'):
        if header.is_file() and header.name!='System.h' and digest(header)!=digest(new/header.relative_to(old)):
            raise ValueError('Existing header changed: '+str(header))
    processes={}
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            argv=proc.joinpath('cmdline').read_bytes().split(b'\0');stat=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()
            processes[int(proc.name)]=(int(stat[1]),[v.decode(errors='replace') for v in argv if v])
        except (FileNotFoundError,PermissionError,IndexError):pass
    roots=[pid for pid,(_,argv) in processes.items() if any(x.endswith('/cmake') or x=='cmake' for x in argv[:1]) and '--build' in argv and str(build) in argv]
    descendants=set(roots)
    while True:
        more={pid for pid,(ppid,_) in processes.items() if ppid in descendants}
        if more<=descendants:break
        descendants|=more
    schedulers=[pid for pid in descendants if Path(processes[pid][1][0]).name in ('make','gmake')]
    if not schedulers:raise ValueError('Expected this isolated build running with make')
    paused=[];reused=[]
    try:
        for pid in schedulers:os.kill(pid,signal.SIGSTOP);paused.append(pid)
        active={Path(arg).resolve() for pid in descendants for arg in processes[pid][1] if arg.startswith(str(new)+'/src/') and arg.endswith(('.cc','.cpp'))}
        for source in sorted((old/'src').rglob('*')):
            if source.suffix not in ('.cc','.cpp'):continue
            relative=source.relative_to(old);candidate=new/relative;obj=Path(str(ob/relative)+'.o');target=Path(str(nb/relative)+'.o')
            if target.exists() or candidate.resolve() in active or not obj.is_file() or digest(source)!=digest(candidate):continue
            if source.stat().st_mtime>obj.stat().st_mtime:continue
            data=obj.read_bytes()
            if data[:5]!=b'\x7fELF\x02' or struct.unpack_from('<H',data,18)[0]!=183:raise ValueError('Cached object is not native AArch64')
            target.parent.mkdir(parents=True,exist_ok=True);temporary=Path(str(target)+'.cache-copy')
            temporary.write_bytes(data)
            try:os.link(temporary,target)
            except FileExistsError:continue
            finally:temporary.unlink()
            dep=Path(str(obj)+'.d')
            if dep.exists():Path(str(target)+'.d').write_text(dep.read_text().replace(str(old),str(new)))
            reused.append(dict(source=relative.as_posix(),source_sha256=digest(source),object_sha256=hashlib.sha256(data).hexdigest()))
    finally:
        for pid in paused:
            try:os.kill(pid,signal.SIGCONT)
            except ProcessLookupError:pass
    report=dict(status='CACHE_REUSE_ONLY',compile_flags=nf,nonvirtual_system_method_only=True,unchanged_headers=True,objects=reused,active_outputs_excluded=[str(x) for x in active])
    (build/'OBJECT_REUSE.json').write_text(json.dumps(report,indent=2)+'\n');print('VERIFIED_OBJECTS_REUSED',len(reused),flush=True)


if __name__=='__main__':main()
