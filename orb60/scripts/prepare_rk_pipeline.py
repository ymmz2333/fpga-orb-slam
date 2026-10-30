"""Preserve the tested RK synchronous build, then apply incremental0018."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--baseline-status',type=Path,required=True);a=p.parse_args()
    root=a.project/'vendor/ORB_SLAM3';manifest=json.loads((a.workspace/'transfer_manifest.json').read_text())
    for name,digest in manifest.items():assert sha(a.workspace/name)==digest,name
    baseline=json.loads(a.baseline_status.read_text())
    assert baseline['integration_pass'] and baseline['exit_code']==0
    for name,digest in baseline['source_sha256'].items():assert sha(root/name)==digest,('changed RK source',name)
    assert not a.snapshot.exists();a.snapshot.mkdir(parents=True)
    preserved={}
    for name in ('lib/libORB_SLAM3.so','Examples/Monocular/mono_euroc','include/FeatureIO.h','src/FeatureIO.cc',
                 'Examples/Monocular/mono_euroc.cc','include/FpgaORB.h','include/Orb60Protocol.h'):
        dst=a.snapshot/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,dst);preserved[name]=sha(dst)
    (a.snapshot/'manifest.json').write_text(json.dumps(preserved,indent=2)+'\n')
    subprocess.run(['python3',str(a.workspace/'orb60/scripts/install_slam_network.py'),
                    '--source',str(root),'--workspace',str(a.workspace)],check=True)
    print('RK_SYNC_BINARY_SOURCE_SNAPSHOT_AND_PIPELINE_DEPLOY_PASS')


if __name__=='__main__':main()
