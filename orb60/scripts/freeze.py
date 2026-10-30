"""Create the curated R11 source snapshot; never copy generated projects."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'orb60' / 'baseline'
ARCHIVE = ROOT / 'r11' / 'r11'
entries = []

def copy(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f'Existing snapshot differs: {target}')
    shutil.copyfile(source, target)
    entries.append({'source': source.relative_to(ROOT).as_posix(),
                    'snapshot': target.relative_to(DEST).as_posix(), 'sha256': digest})

hls = ARCHIVE / 'w' / 'FPGA_ORB_HLS'
for folder in ('fastv2/include', 'fastv2/src', 'fastv2/hls', 'fastv2/host',
               'fastv2/ps', 'fastv2/next/src', 'fastv2/next/include',
               'fastv2/next/host', 'fastv2/next/hls', 'fastv2/next/ps'):
    for file in (hls / folder).rglob('*'):
        if file.is_file() and file.suffix in {'.cpp', '.c', '.h', '.hpp', '.inc', '.bin', '.tcl'}:
            copy(file, DEST / 'FPGA_ORB_HLS' / file.relative_to(hls))
for rel in ('fastv2/next/CMakeLists.txt', 'fastv2/scripts/generate_profile_rom.py'):
    copy(hls / rel, DEST / 'FPGA_ORB_HLS' / rel)
golden = ARCHIVE / 'w' / 'FPGA_ORB_SHARED_v1.0'
for rel in ('golden.cpp', 'golden.hpp', 'constants.hpp', 'LICENSE', 'NOTICE.md',
            'vectors/flight_20261004T184929_998838_6bb93c56_f0000/input.pgm'):
    copy(golden / rel, DEST / 'FPGA_ORB_SHARED_v1.0' / rel)
frozen = DEST / 'FPGA_ORB_HLS/fastv2/next/frozen_ps'
for file in (ARCHIVE / 'release/R11_DEFAULT/inputs').iterdir():
    if file.suffix in {'.c', '.h', '.inc'}:
        copy(file, frozen / file.name)
output = ROOT / 'orb60' / 'provenance.json'
output.write_text(json.dumps({'device': 'xc7z015clg485-2',
    'pl_parent_job': '20261010_020213_a86e3550',
    'ps_release_job': '20261010_132933_ps_a191d754',
    'files': entries}, indent=2) + '\n', encoding='utf-8')
print(f'Frozen {len(entries)} files; hashes recorded in {output}')
