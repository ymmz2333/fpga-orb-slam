"""Read-only SHA256 integrity check for the extracted handoff."""
import argparse
import json
from pathlib import Path
from .common import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args();root=a.root.resolve()
    files=json.loads((root/'SHA256SUMS.json').read_text())
    for relative,expected in files.items():
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or digest(path)!=expected:raise ValueError('Package integrity failure: '+relative)
    print('PACKAGE_HASH_PASS',len(files))

if __name__=='__main__':main()
