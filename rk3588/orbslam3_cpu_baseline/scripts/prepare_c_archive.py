"""Validate/hash prepared PNG datasets and package with portable relative paths."""
import argparse,hashlib,json,pathlib,tarfile
from validate_prepared import validate
def main():
    p=argparse.ArgumentParser(); p.add_argument('--datasets',type=pathlib.Path,required=True); p.add_argument('--archive',type=pathlib.Path,required=True); a=p.parse_args()
    if a.archive.exists(): raise ValueError('Refusing existing archive')
    manifest=json.loads((a.datasets/'manifest.json').read_text(encoding='utf-8'))
    for clip in manifest['clips']:
        meta=validate(a.datasets/clip['dataset'],full_hash=True)
        print('C1_PNG_HASH_PASS %s frames=%d'%(clip['clip'],meta['expected_frames']),flush=True)
    with tarfile.open(a.archive,'w') as tar:
        tar.add(a.datasets,arcname=a.datasets.name)
    with a.archive.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
    result=dict(archive=a.archive.name,bytes=a.archive.stat().st_size,sha256=sha,clips=len(manifest['clips']),
        frames=sum(c['expected_frames'] for c in manifest['clips']),full_png_hash_verified=True)
    a.archive.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('C1_ARCHIVE_READY '+json.dumps(result))
if __name__=='__main__': main()
