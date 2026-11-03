"""Snapshot the actual compiler target and isolated container Python environment."""
import argparse
import json
import platform
from pathlib import Path
import shutil
import subprocess
from .common import digest,save
from .preflight import fingerprints


def main():
    p=argparse.ArgumentParser();p.add_argument('--arch',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.arch,a.output/'arch.json')
    import torch
    profile=json.loads(Path(__file__).with_name('profile.json').read_text())
    profile.update(arch_sha256=digest(a.arch),fingerprints=sorted(fingerprints(json.loads(a.arch.read_text()))),
                   python=platform.python_version(),torch=torch.__version__,machine=platform.machine())
    save(a.output/'target_profile.json',profile)
    print('TARGET_SNAPSHOT',profile['fingerprints'])

if __name__=='__main__':main()
