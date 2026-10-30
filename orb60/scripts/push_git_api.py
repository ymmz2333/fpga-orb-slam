"""Fast-forward an authorized Git branch through GitHub Git Data API.

Uses the existing Git credential helper in memory only. Never logs credentials.
Checks all uploaded blob/tree/commit SHAs against the exact local Git objects.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import time

def run(a):
    repo=a.repo.resolve();output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
    assert not git('status','--porcelain').strip(),'Commit the reviewable package first'
    branch=git('branch','--show-current').decode().strip();assert branch=='codex/orb60-4ppc'
    commit=git('rev-parse','HEAD').decode().strip();parent=git('rev-parse','HEAD^').decode().strip()
    raw=git('cat-file','commit',commit);head,message=raw.split(b'\n\n',1)
    tree_sha=git('rev-parse','HEAD^{tree}').decode().strip()
    auth=subprocess.run(['git','-C',str(repo),'credential','fill'],input='protocol=https\nhost=github.com\n\n',
                        text=True,capture_output=True,check=True)
    fields=dict(line.split('=',1) for line in auth.stdout.splitlines() if '=' in line)
    secret=fields['password'];auth=None;fields=None
    endpoint='https://api.github.com/repos/ymmzseu/fpga-orb-r11-orb60'
    def api(method,path,value=None):
        body=json.dumps(value).encode() if value is not None else None
        request=Request(endpoint+path,data=body,method=method,headers={
            'Authorization':'Bearer '+secret,'Accept':'application/vnd.github+json',
            'Content-Type':'application/json','User-Agent':'ORB60-source-publication',
            'X-GitHub-Api-Version':'2022-11-28'})
        for attempt in range(3):
            try:
                with urlopen(request,timeout=30) as response:return json.load(response)
            except HTTPError as error:
                if error.code in (502,503,504) and attempt<2:
                    time.sleep(1+attempt*2);continue
                # Status only: never print request headers containing auth.
                detail=error.read().decode('utf-8',errors='replace')[:1800]
                if error.code==400 and path=='/git/blobs' and body and len(body)>1000000:
                    # Native curl handles this host's large-request transport.
                    # Auth stays on stdin, never argv or disk; the body contains
                    # only the already-authorized repository blob.
                    payload_file=output/'large_blob_request.json'
                    payload_file.write_bytes(body)
                    config='\n'.join([
                        'url = '+json.dumps(endpoint+path),'request = "POST"',
                        'header = '+json.dumps('Authorization: Bearer '+secret),
                        'header = "Accept: application/vnd.github+json"',
                        'header = "Content-Type: application/json"',
                        'header = "X-GitHub-Api-Version: 2022-11-28"',
                        'user-agent = "ORB60-source-publication"',
                        'data-binary = '+json.dumps('@'+payload_file.as_posix()),
                        'connect-timeout = 15','max-time = 55','silent','show-error',
                        'write-out = "\\n%{http_code}"'])+'\n'
                    native=subprocess.run(['curl.exe','--config','-'],input=config,text=True,capture_output=True)
                    content,code=native.stdout.rsplit('\n',1) if '\n' in native.stdout else ('','000')
                    if native.returncode==0 and code=='201':return json.loads(content)
                    raise RuntimeError(f'Native large-blob transport failed: exit{native.returncode} HTTP{code}; '+content[:400]) from None
                raise RuntimeError(f'GitHub API {method} {path}: HTTP{error.code} {detail}') from None
    ref='/git/ref/heads/'+branch
    assert api('GET',ref)['object']['sha']==parent,'Remote branch changed; preserve its new work'
    prior=api('GET','/git/commits/'+parent)
    def entries(revision):
        result={}
        for item in git('ls-tree','-rz',revision).split(b'\0'):
            if not item:continue
            meta,path=item.split(b'\t',1);mode,kind,digest=meta.decode().split()
            assert kind=='blob';result[path.decode('utf-8')]={'mode':mode,'type':kind,'sha':digest}
        return result
    old,new=entries(parent),entries(commit)
    known={e['sha'] for e in old.values()}
    changes=[dict(path=name,**entry) for name,entry in new.items() if old.get(name)!=entry]
    changes += [dict(path=name,mode=e['mode'],type='blob',sha=None) for name,e in old.items() if name not in new]
    blobs={entry['sha']:entry['path'] for entry in changes if entry['sha'] and entry['sha'] not in known}
    state=dict(State='RUNNING',Stage='BLOBS',Repository='ymmzseu/fpga-orb-r11-orb60',Branch=branch,
        LocalCommit=commit,Parent=parent,Files=len(new),ChangedFiles=len(changes),UniqueNewBlobs=len(blobs),Uploaded=0)
    def save(): (output/'github_api_status.json').write_text(json.dumps(state,indent=2)+'\n')
    save();print(f'GITHUB_API_BLOBS total={len(blobs)} changed_paths={len(changes)}',flush=True)
    if a.resume_tree:
        # Completed blobs are content-addressed. A tree referencing all SHAs
        # proves availability without uploading them again after a transient502.
        try:
            repaired=set()
            for attempt in range(65):
                try:
                    remote_tree=api('POST','/git/trees',dict(base_tree=prior['tree']['sha'],tree=changes))
                    assert remote_tree['sha']==tree_sha
                    break
                except RuntimeError as error:
                    missing=re.search(r'tree\.sha ([0-9a-f]{40}) is not a valid blob',str(error))
                    if not missing or missing[1] not in blobs or missing[1] in repaired or attempt==64:raise
                    digest=missing[1];content=git('cat-file','blob',digest)
                    state['CurrentRecovery']=dict(sha=digest,path=blobs[digest],bytes=len(content));save()
                    print('GITHUB_API_RECOVERY_FILE '+json.dumps(state['CurrentRecovery']),flush=True)
                    assert api('POST','/git/blobs',dict(content=base64.b64encode(content).decode(),encoding='base64'))['sha']==digest
                    repaired.add(digest);state['RecoveredMissingBlobs']=len(repaired);save()
                    print(f'GITHUB_API_REPAIRED_MISSING {len(repaired)}',flush=True)
            state['TreeRecovered']=True;blobs={};save()
        except BaseException as error:
            state.update(State='FAILED',Stage='TREE_RECOVERY',Error=str(error));save();raise
    def upload(item):
        digest,path=item;content=git('cat-file','blob',digest)
        assert hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==digest
        assert api('POST','/git/blobs',dict(content=base64.b64encode(content).decode(),encoding='base64'))['sha']==digest
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in as_completed([pool.submit(upload,item) for item in blobs.items()]):
                future.result();state['Uploaded']+=1;save()
                if state['Uploaded']%25==0:print(f"GITHUB_API_UPLOADED {state['Uploaded']}/{len(blobs)}",flush=True)
        state['Stage']='TREE';save()
        assert api('POST','/git/trees',dict(base_tree=prior['tree']['sha'],tree=changes))['sha']==tree_sha
        def identity(kind):
            line=next(line.decode() for line in head.splitlines() if line.startswith((kind+' ').encode()))
            match=re.fullmatch(kind+r' (.*) <([^>]+)> (\d+) ([+-]\d{4})',line)
            assert match and match[4]=='+0000','Create the local publication commit with UTC dates'
            return dict(name=match[1],email=match[2],date=datetime.fromtimestamp(int(match[3]),timezone.utc).isoformat())
        state['Stage']='COMMIT';save()
        payload=dict(message=message.decode('utf-8'),tree=tree_sha,parents=[parent],author=identity('author'),committer=identity('committer'))
        remote=api('POST','/git/commits',payload);assert remote['sha']==commit,'Remote commit serialization differs; ref remains untouched'
        assert api('GET',ref)['object']['sha']==parent,'Concurrent branch update; ref remains untouched'
        state['Stage']='FAST_FORWARD';save()
        assert api('PATCH','/git/refs/heads/'+branch,dict(sha=commit,force=False))['object']['sha']==commit
        assert api('GET',ref)['object']['sha']==commit
        state.update(State='SUCCEEDED',Stage='REMOTE_VERIFIED',RemoteCommit=commit,
                     Url='https://github.com/ymmzseu/fpga-orb-r11-orb60/tree/'+branch)
        print('GITHUB_API_REMOTE_VERIFIED '+commit,flush=True)
    except BaseException as error:
        state.update(State='FAILED',Error=str(error));raise
    finally:save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resume-tree',action='store_true')
    run(p.parse_args())
