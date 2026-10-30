"""Validate every prepared clip and optionally every PNG hash on the board."""
import argparse,json,pathlib
from validate_prepared import validate
p=argparse.ArgumentParser(); p.add_argument('datasets',type=pathlib.Path); p.add_argument('--full-hash',action='store_true'); a=p.parse_args()
manifest=json.loads((a.datasets/'manifest.json').read_text(encoding='utf-8'))
total=0
for clip in manifest['clips']:
    result=validate(a.datasets/clip['dataset'],a.full_hash)
    if result['expected_frames']!=clip['expected_frames']: raise ValueError('Corpus metadata mismatch')
    total+=result['expected_frames']; print('C_DATA_PASS '+clip['clip']+' frames='+str(result['expected_frames']),flush=True)
print('C_CORPUS_PASS clips=%d frames=%d full_hash=%s'%(len(manifest['clips']),total,a.full_hash))
