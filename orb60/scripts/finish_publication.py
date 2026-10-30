"""Check bit header, build a complete ZIP, commit and optionally push the branch."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

BRANCH='codex/orb60-100mhz-2ppc-pl-descriptor'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def git(repo,*args):return subprocess.run(['git','-C',str(repo),*args],capture_output=True,text=True,encoding='utf-8',errors='replace')
def files(repo):
    result=[repo/name for name in ('.gitattributes','.gitignore','AGENTS.md','README.md','tools/verify_orb60.ps1')]
    for folder in ('orb60','scripts','tb/common'):
        result.extend(p for p in (repo/folder).rglob('*') if p.is_file() and
                      '__pycache__' not in p.parts and p.suffix not in ('.pyc','.log') and 'build' not in p.relative_to(repo).parts)
    return sorted(set(result))
def bit_header(path):
    data=path.read_bytes();at=2+struct.unpack_from('>H',data)[0]
    assert struct.unpack_from('>H',data,at)[0]==1;at+=2
    fields={}
    for tag in ('a','b','c','d'):
        assert chr(data[at])==tag;at+=1
        size=struct.unpack_from('>H',data,at)[0];at+=2
        fields[tag]=data[at:at+size].rstrip(b'\0').decode('ascii');at+=size
    assert data[at]==ord('e');at+=1
    size=struct.unpack_from('>I',data,at)[0];at+=4
    assert at+size==len(data) and size>100000
    assert '7z015' in fields['b'] and 'clg485' in fields['b']
    return dict(design=fields['a'],part=fields['b'],date=fields['c'],time=fields['d'],payload_bytes=size)

def run(a):
    repo=a.repo.resolve();out=a.output.resolve();root=a.root.resolve();orb=root/'orb60'
    assert git(repo,'branch','--show-current').stdout.strip()==BRANCH
    assert git(repo,'diff','--cached','--name-only').stdout.strip()==''
    bit=out/'bit/orb60_100mhz.bit';header=bit_header(bit)
    artifact=repo/'orb60/artifacts/100mhz';artifact.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(bit,artifact/bit.name)
    for name in ('bit_metrics.tsv','bit_check_timing.rpt','bit_route_status.rpt','bit_drc.rpt'):
        shutil.copyfile(out/'bit'/name,artifact/name)
    metrics=dict(line.split('\t',1) for line in (out/'bit/bit_metrics.tsv').read_text().splitlines())
    assert float(metrics['wns_ns'])>=0 and float(metrics['whs_ns'])>=0 and metrics['part']=='xc7z015clg485-2'
    info=dict(status='PASS',part='xc7z015clg485-2',frequency_mhz=100,bit_header=header,
        bit_sha256=sha(bit),checkpoint_sha256=sha(a.checkpoint),checkpoint_bytes=a.checkpoint.stat().st_size,
        metrics=metrics,ps_firmware_modified=False,physical_board_verified=False,
        scope='Bit generated from accepted 100 MHz routed checkpoint; no paired new ELF or board programming')
    write_json(artifact/'artifact_manifest.json',info)
    (artifact/'README.md').write_text('# 100 MHz bitstream\n\n'
        'Part: xc7z015clg485-2. Top: s_wrapper. Vivado 2024.2.\n\n'
        f'File: orb60_100mhz.bit; SHA256: `{info["bit_sha256"]}`.\n\n'
        'This is the two-core ORB60 PL development artifact. The historical R11 ELF\n'
        'does not configure its new interfaces. No new PS ELF or physical-board\n'
        'performance result is included. See ../../README_ZH.md.\n',encoding='utf-8')
    manifest_path=repo/'orb60/PUBLICATION_MANIFEST.json'
    rows=[dict(path=p.relative_to(repo).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in files(repo) if p!=manifest_path]
    write_json(manifest_path,dict(scope='Source/docs/evidence/bit publication, not a new board test',files=rows))
    verify=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(repo/'tools/verify_orb60.ps1')],capture_output=True,text=True)
    assert verify.returncode==0,verify.stderr
    (out/'verify_publication.log').write_text(verify.stdout+verify.stderr,encoding='utf-8')
    # The fallback ZIP includes the full repository worktree (without .git) and
    # restores external fixtures and original frozen cache bytes from the root.
    zip_path=out/'orb60_100mhz_source_bit.zip'
    missing=json.loads((repo/'orb60/docs/EXTERNAL_FIXTURES.json').read_text(encoding='utf-8'))
    extras={}
    origins={'layer2':orb/'build/optimized/hls/20261012_112318_layer2_7d592c6c',
             'descriptor':orb/'build/optimized/hls/20261012_132126_descriptor_9cae63b8'}
    for item in missing:
        path=Path(item['path']);parts=path.parts
        source=root/path if parts[1]=='optimized' else origins[parts[3]]/Path(*parts[4:])
        assert sha(source)==item['sha256'];extras[item['path']]=source
    tracked=git(repo,'ls-files','-z').stdout.split('\0')
    payload={name:repo/name for name in tracked if name}
    payload.update({p.relative_to(repo).as_posix():p for p in files(repo)})
    payload.update(extras)
    zip_rows=[dict(path=name,bytes=p.stat().st_size,sha256=sha(p)) for name,p in sorted(payload.items())]
    for kernel,origin in origins.items():
        entries=json.loads((origin/'source_manifest.json').read_text(encoding='utf-8-sig'))
        for entry in entries:
            name=f'orb60/frozen/100mhz/{kernel}/inputs/'+entry['Path'].replace('\\','/')
            assert name in payload and sha(payload[name]).upper()==entry['SHA256']
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,p in sorted(payload.items()):archive.write(p,'fpga-orb-r11/'+name)
        archive.writestr('fpga-orb-r11/ZIP_CONTENT_MANIFEST.json',json.dumps(dict(files=zip_rows),indent=2)+'\n')
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        for row in zip_rows:
            assert hashlib.sha256(archive.read('fpga-orb-r11/'+row['path'])).hexdigest()==row['sha256']
    write_json(out/'zip_manifest.json',dict(file=str(zip_path),sha256=sha(zip_path),bytes=zip_path.stat().st_size,files=len(zip_rows),full_frozen_inputs_verified=True))
    spec=out/'git_pathspec.bin'
    spec.write_bytes(b'\0'.join((':(literal)'+p.relative_to(repo).as_posix()).encode('utf-8') for p in files(repo))+b'\0')
    stage=git(repo,'add','--pathspec-from-file='+str(spec),'--pathspec-file-nul')
    assert stage.returncode==0,stage.stderr
    allowed={p.relative_to(repo).as_posix() for p in files(repo)}
    assert set(git(repo,'diff','--cached','--name-only','-z').stdout.strip('\0').split('\0'))<=allowed
    message=out/'commit_message.txt'
    message.write_text('Add exact ORB60 100 MHz 2PPC and PL descriptor snapshot\n\n'
        'Publish paired HLS sources, generators, frozen compilation inputs, build\n'
        'and verification scripts, Chinese architecture/interface documentation,\n'
        'complete routed timing/resource evidence and the generated bitstream.\n\n'
        '100 MHz route: WNS +0.238 ns, WHS +0.035 ns. Shared-DDR native RTL is\n'
        'byte-exact for six complete frames; ordinary 11.37-12.71 ms and 942-point\n'
        'pressure 13.29-15.82 ms under the documented DDR models. PS firmware is\n'
        'unchanged and incompatible historical ELF is not offered as a pair.\n'
        'Physical-board P99/max and sustained 60 FPS remain unverified.\n',encoding='utf-8')
    commit=git(repo,'commit','--file',str(message));assert commit.returncode==0,commit.stderr
    commit_sha=git(repo,'rev-parse','HEAD').stdout.strip()
    result=dict(status='LOCAL_COMPLETE',branch=BRANCH,commit=commit_sha,zip=str(zip_path),bit_manifest=info,
                github_pushed=False,finished_utc=datetime.now(timezone.utc).isoformat())
    if a.push:
        pushed=git(repo,'push','-u','origin',BRANCH)
        (out/'push.log').write_text(pushed.stdout+pushed.stderr,encoding='utf-8')
        if pushed.returncode==0:
            remote=git(repo,'ls-remote','--heads','origin',BRANCH)
            assert remote.returncode==0 and remote.stdout.split()[0]==commit_sha
            result.update(status='SUCCEEDED',github_pushed=True,branch_url='https://github.com/sunsn061128/fpga-orb-r11/tree/'+BRANCH)
        else:result.update(status='ZIP_READY_PUSH_BLOCKED',push_error='See push.log; ZIP and local commit are complete')
    write_json(out/'publication_result.json',result)
    print(f'ORB60_PUBLICATION_RESULT={result["status"]} COMMIT={commit_sha} ZIP={zip_path}',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('repo','root','output','checkpoint'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--push',action='store_true');run(p.parse_args())
