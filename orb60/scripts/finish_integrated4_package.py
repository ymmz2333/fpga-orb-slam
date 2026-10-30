"""Hash the reviewable package, create verified ZIP and make a local UTC commit."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(a):
    repo=a.repo.resolve();output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    excluded={'.git','.venv','.work','build','__pycache__'}
    manifests={'orb60/PUBLICATION_MANIFEST.json','orb60/INTEGRATED4_MANIFEST.json'}
    frozen_jobs=[p.parent for name in ('integrated4_100mhz','integrated4_125mhz','2ppc_125mhz','speed_joint_150mhz')
                 for p in (repo/'orb60/frozen'/name).glob('*/source_manifest.json')]
    for frozen in frozen_jobs:
        for entry in json.loads((frozen/'source_manifest.json').read_text(encoding='utf-8-sig')):
            assert sha(frozen/'inputs'/entry['Path']).upper()==entry['SHA256'],'Incomplete frozen source distribution'
    paths={p.relative_to(repo).as_posix():p for p in repo.rglob('*') if p.is_file() and
           not any(part in excluded for part in p.relative_to(repo).parts) and p.suffix not in ('.pyc','.zip') and p.name!='local_env.ps1'}
    for frozen in frozen_jobs:
        for entry in json.loads((frozen/'source_manifest.json').read_text(encoding='utf-8-sig')):
            path=frozen/'inputs'/entry['Path'];paths[path.relative_to(repo).as_posix()]=path
    rows=[dict(path=name,bytes=p.stat().st_size,sha256=sha(p)) for name,p in sorted(paths.items()) if name not in manifests]
    value=dict(scope='Paired source/bit/computer evidence integrity; no new board test',files=rows)
    for name in manifests:
        (repo/name).write_text(json.dumps(value,indent=2)+'\n')
        paths[name]=repo/name
    verify=subprocess.run(['pwsh','-NoProfile','-ExecutionPolicy','Bypass','-File',str(repo/'tools/verify_integrated4.ps1')],capture_output=True,text=True)
    (output/'verify_integrated4.log').write_text(verify.stdout+verify.stderr,encoding='utf-8')
    assert verify.returncode==0,verify.stderr
    if (repo/'orb60/artifacts/speed_joint_150mhz').is_dir():
        speed=subprocess.run(['pwsh','-NoProfile','-ExecutionPolicy','Bypass','-File',str(repo/'orb60/scripts/verify_speed150.ps1')],capture_output=True,text=True)
        (output/'verify_speed150.log').write_text(speed.stdout+speed.stderr,encoding='utf-8')
        assert speed.returncode==0,speed.stderr
    archive=output/a.archive_name
    assert not archive.exists(),'Preserve previous package snapshots'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,p in sorted(paths.items()):z.write(p,name)
        z.writestr('PACKAGE_CONTENTS.json',json.dumps(dict(files=[dict(path=n,bytes=p.stat().st_size,sha256=sha(p)) for n,p in sorted(paths.items())]),indent=2)+'\n')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,p in paths.items():assert hashlib.sha256(z.read(name)).hexdigest()==sha(p)
    env=os.environ.copy();stamp=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    env.update(GIT_AUTHOR_DATE=stamp,GIT_COMMITTER_DATE=stamp,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never')
    subprocess.run(['git','-C',str(repo),'add','.'],check=True,env=env)
    subprocess.run(['git','-C',str(repo),'add','-f','orb60/frozen/integrated4_100mhz'],check=True,env=env)
    for name in ('integrated4_125mhz','2ppc_125mhz','speed_joint_150mhz'):
        if (repo/'orb60/frozen'/name).is_dir():subprocess.run(['git','-C',str(repo),'add','-f','orb60/frozen/'+name],check=True,env=env)
    subprocess.run(['git','-C',str(repo),'commit','-m',a.message],check=True,env=env)
    commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    result=dict(status='LOCAL_COMMIT_ZIP_VERIFIED',commit=commit,zip=str(archive),zip_sha256=sha(archive),files=len(paths),bytes=archive.stat().st_size)
    (output/'package_result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('repo','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--message',default='Implement exact4PPC ORB pipeline with overlapped image IO; pass100MHz route and14ms modeled pressure goal')
    p.add_argument('--archive-name',default='orb60_4ppc_100mhz_source_reports_bit.zip')
    run(p.parse_args())
