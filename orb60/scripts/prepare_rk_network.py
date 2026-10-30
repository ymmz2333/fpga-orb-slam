"""Deploy the tested network adapter to a pristine existing RK3588 checkout.

Run on the RK through its durable SSH workflow. Preserve the original binary
pair and affected sources before applying the same Windows-authored patches.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    a=p.parse_args();project=a.project.resolve();workspace=a.workspace.resolve();snapshot=a.snapshot.resolve()
    source=project/'vendor/ORB_SLAM3'
    assert not snapshot.exists(),'Preserve the previous deployment snapshot'
    assert subprocess.check_output(['git','status','--porcelain'],cwd=source)==b'', 'Preserve unrelated source changes'
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source).decode().strip()
    assert head=='d3e50c03fc194272c70cb482fd807a025cf7a5cf','Different source baseline: inspect before applying'
    manifest=json.loads((workspace/'transfer_manifest.json').read_text())
    for name,digest in manifest.items():assert sha(workspace/name)==digest,name
    snapshot.mkdir(parents=True)
    preserved={}
    for name in ('lib/libORB_SLAM3.so','Examples/Monocular/mono_euroc','include/FeatureIO.h',
                 'src/FeatureIO.cc','src/Tracking.cc','src/ORBmatcher.cc','Examples/Monocular/mono_euroc.cc'):
        destination=snapshot/'baseline'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,destination);preserved[name]=sha(destination)
    (snapshot/'baseline.json').write_text(json.dumps(dict(head=head,preserved=preserved),indent=2)+'\n')
    subprocess.run(['python3',str(workspace/'orb60/scripts/install_slam_network.py'),
                    '--source',str(source),'--workspace',str(workspace)],check=True)
    (snapshot/'deployed.json').write_text(json.dumps(dict(state='SOURCE_DEPLOYED_BUILD_PENDING',
        head=head,workspace=str(workspace),source=str(source),transfer_sha256=manifest),indent=2)+'\n')
    print('RK_SOURCE_TRANSFER_SHA_AND_BASELINE_BACKUP_PASS',flush=True)


if __name__=='__main__':main()
