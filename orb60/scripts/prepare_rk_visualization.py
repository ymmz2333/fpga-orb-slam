"""Back up the accepted pipeline and apply its read-only desktop telemetry patch."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--baseline-status',type=Path,required=True);a=p.parse_args()
    source=a.project.resolve()/'vendor/ORB_SLAM3';workspace=a.workspace.resolve()
    state=json.loads(a.baseline_status.read_text());assert state['integration_pass'] and state['exit_code']==0
    for name,sha in state['source_sha256'].items():assert digest(source/name)==sha,('changed source',name)
    manifest=json.loads((workspace/'transfer_manifest.json').read_text())
    for name,sha in manifest.items():assert digest(workspace/name)==sha,name
    assert not a.snapshot.exists();a.snapshot.mkdir(parents=True)
    saved={}
    for name in ('include/System.h','src/System.cc','Examples/Monocular/mono_euroc.cc',
                 'Examples/Monocular/mono_euroc','lib/libORB_SLAM3.so'):
        dst=a.snapshot/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,dst);saved[name]=digest(dst)
    (a.snapshot/'manifest.json').write_text(json.dumps(saved,indent=2)+'\n')
    subprocess.run(['python3',str(workspace/'orb60/scripts/install_slam_telemetry.py'),
                    '--source',str(source),'--workspace',str(workspace)],check=True)
    print('VISUALIZATION_SOURCE_SHA_BACKUP_AND_INSTALL_PASS')


if __name__=='__main__':main()
