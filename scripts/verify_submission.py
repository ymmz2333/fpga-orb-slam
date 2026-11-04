"""Read-only integrity and release-entry check for the source submission."""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    manifest = json.loads((ROOT/'SOURCE_SNAPSHOT_SHA256.json').read_text(encoding='utf-8'))
    errors = []
    for name, expected in manifest['files'].items():
        path = ROOT/name
        if not path.resolve().is_relative_to(ROOT.resolve()):
            errors.append('Unsafe manifest path: '+name)
        elif not path.is_file():
            errors.append('Missing file: '+name)
        elif digest(path) != expected['sha256'] or path.stat().st_size != expected['bytes']:
            errors.append('Hash/size mismatch: '+name)
    required = (
        'LICENSE', 'THIRD_PARTY_NOTICES.md', 'LICENSING.md',
        'orb60/optimized/FPGA_ORB_HLS/fastv2/next/src/layer2_hls.cpp',
        'orb60/optimized/FPGA_ORB_HLS/fastv2/next/src/descriptor_hls.cpp',
        'zynq7015_demo/src/demo_main.cpp', 'zynq7015_demo/src/slam.cpp',
        'orb60/kv260/manual_control.py', 'orb60/kv260/saved_map.py',
        'review/kv260_slam_base/src/Tracking.cc',
        'review/kv260_hardware_source/system.tcl',
        'orb60/kv260/point_pl/point_project.cpp',
        'assets/models/midas_qat_best.pth', 'assets/models/midas_kv260_b4096.xmodel',
    )
    for name in required:
        if name not in manifest['files']:
            errors.append('Required release entry omitted: '+name)
    text_suffixes = {'.py','.ps1','.sh','.tcl','.cpp','.cc','.c','.h','.hpp','.md','.json','.yaml','.yml','.txt','.v','.sv','.dts','.dtsi'}
    patterns = {
        'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
        'github_token': re.compile(r'(?:gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{30,})'),
        'api_token': re.compile(r'sk-(?:proj-)?[A-Za-z0-9_-]{30,}'),
    }
    for name in manifest['files']:
        path = ROOT/name
        if path.name in {'.env','local_env.ps1','local_board.json','id_rsa','id_ed25519','known_hosts'} or path.suffix in {'.key','.pem'}:
            errors.append('Private local file: '+name)
        if path.suffix.lower() in text_suffixes and path.stat().st_size<5_000_000:
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeError:
                continue
            for label, pattern in patterns.items():
                if pattern.search(text):
                    # Print path and category, never a matched credential.
                    errors.append(label+': '+name)
    print(json.dumps({'status':'FAIL' if errors else 'PASS',
                      'files_checked':len(manifest['files']),
                      'total_bytes':sum(f['bytes'] for f in manifest['files'].values()),
                      'required_entries':len(required),'errors':errors},ensure_ascii=True,indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
