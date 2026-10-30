"""Read-only comparison of the frozen source, original source and artifact hashes."""
from pathlib import Path
import hashlib,json

root=Path(__file__).resolve().parents[1]
baseline=root.parent/'baselines/zynq_slam_30fps_20261024_003206'
original=root.parent/'zynq_slam'
manifest=json.loads((baseline/'manifest.json').read_text(encoding='utf-8'))

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

for name,expected in manifest['source_sha256'].items():
    for folder in (baseline/'source',original):
        if digest(folder/name)!=expected:raise SystemExit('BASELINE_CHANGED: '+str(folder/name))
artifacts=0
for line in (baseline/'SHA256SUMS').read_text().splitlines():
    expected,name=line.split('  ',1)
    if digest(baseline/name)!=expected:raise SystemExit('FROZEN_ARTIFACT_CHANGED: '+name)
    artifacts+=1
print(json.dumps(dict(status='PASS',original_and_frozen_source_files=len(manifest['source_sha256']),
    artifact_checks=artifacts,baseline=str(baseline),read_buffer_bytes=1024*1024),indent=2))
