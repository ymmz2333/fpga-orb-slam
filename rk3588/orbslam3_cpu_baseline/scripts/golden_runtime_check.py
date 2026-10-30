"""Validate accepted Linux artifacts inside WSL, including Linux symlink targets."""
import argparse
import hashlib
import json
import pathlib
from run_pc_slam import library_environment,verify_linkage

def main():
    p=argparse.ArgumentParser();p.add_argument('--acceptance',required=True,type=pathlib.Path);a=p.parse_args()
    accepted=json.loads(a.acceptance.read_text());assert accepted['status']=='PASSED'
    for path,digest in accepted['runtime_sha256'].items():
        actual=hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
        if actual!=digest:raise RuntimeError('Accepted runtime changed: '+path)
    binaries=[pathlib.Path(p) for p in accepted['runtime_sha256'] if p.endswith('/Examples/Monocular/mono_euroc')]
    if len(binaries)!=1:raise RuntimeError('One accepted native executable required')
    binary=binaries[0];env,library=library_environment(binary);verify_linkage(binary,env,library)
    print('ACCEPTED_LINUX_RUNTIME_PASS files=%d prefix=%s'%(len(accepted['runtime_sha256']),library))
if __name__=='__main__':main()
