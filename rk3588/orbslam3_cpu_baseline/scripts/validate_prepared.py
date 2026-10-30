"""Validate prepared PNG/timestamp coverage on either PC or board, without ground truth."""
import argparse,csv,hashlib,json,pathlib
def validate(dataset,full_hash=False):
    dataset=pathlib.Path(dataset); meta=json.loads((dataset/'dataset.json').read_text(encoding='utf-8'))
    def sha(p):
        with p.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(f.read()).hexdigest()
    for name,key in [('timestamps.txt','timestamps_sha256'),('frames.csv','frames_csv_sha256')]:
        if sha(dataset/name)!=meta[key]: raise ValueError('Manifest hash mismatch '+name)
    stamps=[int(s) for s in (dataset/'timestamps.txt').read_text().splitlines()]
    with (dataset/'frames.csv').open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
    if len(stamps)!=len(rows) or len(rows)!=meta['expected_frames'] or not rows: raise ValueError('Frame count mismatch')
    if any(b<=a for a,b in zip(stamps,stamps[1:])): raise ValueError('Non-increasing timestamps')
    for i,(stamp,row) in enumerate(zip(stamps,rows)):
        path=dataset/'mav0/cam0/data'/(str(stamp)+'.png')
        if int(row['frame_index'])!=i or int(row['timestamp_ns'])!=stamp or not path.is_file(): raise ValueError('Frame association mismatch')
        with path.open('rb') as f: header=f.read(24)
        if header[:8]!=b'\x89PNG\r\n\x1a\n' or tuple(int.from_bytes(header[s:s+4],'big') for s in (16,20))!=(meta['width'],meta['height']): raise ValueError('Invalid PNG dimensions')
        if full_hash and sha(path)!=row['sha256']: raise ValueError('PNG hash mismatch')
    if len(list((dataset/'mav0/cam0/data').glob('*.png')))!=len(rows): raise ValueError('Extra PNG files')
    return meta
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('dataset'); p.add_argument('--full-hash',action='store_true'); a=p.parse_args()
    m=validate(a.dataset,a.full_hash); print('PREPARED_DATA_PASS frames=%d resolution=%dx%d'%(m['expected_frames'],m['width'],m['height']))
