"""Verify the isolated exporter adds no System layout/data/virtual changes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path)
    p.add_argument('--snapshot',required=True,type=Path);p.add_argument('--build',required=True,type=Path)
    p.add_argument('--ready',required=True,type=Path);a=p.parse_args()
    original=(a.snapshot/'include/System.h').read_text();current=(a.source/'include/System.h').read_text()
    addition='    void ExportLiveDenseSnapshot(const string &directory);\n'
    assert current.count(addition)==1 and current.replace(addition,'')==original
    assert 'ORB_SLAM3_REGISTER_TIMES:BOOL=ON' in (a.source/'build/CMakeCache.txt').read_text()
    digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    library=a.build/'lib/libORB_SLAM3.so'
    assert digest(library)==digest(a.snapshot/'lib/libORB_SLAM3.so')
    executable=a.build/'mono_euroc_live'
    env=__import__('os').environ.copy();env['LD_LIBRARY_PATH']=str(library.parent.resolve())+':'+env.get('LD_LIBRARY_PATH','')
    ldd=subprocess.check_output(['ldd',str(executable)],env=env,text=True)
    assert 'not found' not in ldd and str(library.resolve()) in ldd
    evidence=dict(status='PASS',added_nonvirtual_method_only=True,accepted_library_sha256=digest(library),
                  executable_sha256=digest(executable),register_times_layout_matches=True,
                  isolated_library_resolved=str(library.resolve()))
    a.ready.write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))


if __name__=='__main__':main()
