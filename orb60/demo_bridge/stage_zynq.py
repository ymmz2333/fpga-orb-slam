"""Create a Linux-safe versioned PS release from verified target build artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser();p.add_argument('--arm-directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();arm=a.arm_directory;check=json.loads((arm/'checks.json').read_text())
    if check['status']!='PASS' or not check.get('fully_static') or not check.get('pthread_whole_archive'):raise ValueError('Verified static pthread target candidate required')
    if hashlib.sha256((arm/'zynq-demo').read_bytes()).hexdigest()!=check['binary_sha256']:raise ValueError('Target binary changed')
    files={'bin/'+n:arm/n for n in ('zynq-demo','test-zslam','test-bridge','zynq-map-install')}
    files['bin/s1-reset-bridge']=arm/'s1-reset-bridge'
    if not files['bin/s1-reset-bridge'].is_file():raise ValueError('Build the demo-scoped S1 helper; the old camera-only helper has another path scope')
    files['run_zynq.sh']=Path(__file__).parent/'run_zynq.sh'
    files['run_recording.sh']=Path(__file__).parent/'run_recording.sh'
    if b'\r' in files['run_zynq.sh'].read_bytes():raise ValueError('Shell script must use LF')
    for n in ('camera_source.csv','camera_orb.csv'):files['config/'+n]=Path(__file__).parent/'config'/n
    for source in (ROOT/'zynq7015_demo/tests/fixtures/camera').glob('*'):
        if source.is_file():files['bin/test-fixtures/camera/'+source.name]=source
    sums=''.join(hashlib.sha256(source.read_bytes()).hexdigest()+'  '+name+'\n' for name,source in sorted(files.items()))
    a.output.parent.mkdir(parents=True,exist_ok=True);manifest=a.output.with_suffix('.SHA256SUMS');manifest.write_bytes(sums.encode('ascii'))
    with tarfile.open(a.output,'w:gz') as tf:
        executable={'bin/'+n for n in ('zynq-demo','test-zslam','test-bridge','zynq-map-install','s1-reset-bridge')}
        executable.add('run_zynq.sh')
        executable.add('run_recording.sh')
        for name,source in files.items():
            info=tf.gettarinfo(str(source),arcname=name)
            info.mode=0o755 if name in executable else 0o644
            info.mtime=0
            with source.open('rb') as f:tf.addfile(info,f)
        info=tf.gettarinfo(str(manifest),arcname='SHA256SUMS');info.mode=0o644;info.mtime=0
        with manifest.open('rb') as f:tf.addfile(info,f)
    print('LINUX_RELEASE_STAGED',a.output.stat().st_size,'bytes')


if __name__=='__main__':main()
