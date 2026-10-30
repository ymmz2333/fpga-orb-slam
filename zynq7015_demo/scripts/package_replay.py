"""Export an unchanged prefix of real ORB records for bounded ARM replay."""
from pathlib import Path
import argparse
import csv
import datetime
import json
import tarfile
from synth_pl_2018 import DEFAULT_HANDOFF, digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--golden',type=Path,default=DEFAULT_HANDOFF/'golden')
    parser.add_argument('--frames',type=int,default=240)
    a=parser.parse_args()
    if not 1<=a.frames<=10000:
        raise ValueError('Frames outside bounded export range')
    source=a.golden.resolve()
    root=Path(__file__).resolve().parents[1]
    out=root/'output'/('arm_replay_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(exist_ok=False)
    lines=(source/'frames.csv').read_bytes().splitlines(keepends=True)
    rows=list(csv.DictReader(b''.join(lines[:a.frames+1]).decode('utf-8-sig').splitlines()))
    if len(rows)!=a.frames:
        raise ValueError('Not enough source frames')
    records=0
    for i,row in enumerate(rows):
        count=int(row['count'])
        if int(row['frame_index'])!=i or int(row['record_offset'])!=records or not 0<=count<=1000:
            raise ValueError('Invalid source record contract')
        records+=count
    (out/'frames.csv').write_bytes(b''.join(lines[:a.frames+1]))
    with (source/'features.bin').open('rb') as f:
        data=f.read(records*64)
    if len(data)!=records*64:
        raise ValueError('Truncated source records')
    (out/'features.bin').write_bytes(data)
    (out/'provenance.json').write_text(json.dumps(dict(source=str(source),frames=a.frames,records=records,
        prefix_bytes=len(data),source_frames_sha256=digest(source/'frames.csv'),
        scope='Unmodified real feature prefix; CPU replay, excludes capture/extraction/display'),indent=2)+'\n',encoding='utf-8',newline='\n')
    files=sorted(out.iterdir())
    (out/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in files),encoding='ascii',newline='\n')
    archive=out.with_suffix('.tar.gz')
    with tarfile.open(archive,'w:gz') as tar:
        tar.add(out,arcname=out.name)
    print('ARCHIVE',archive,flush=True)
    print('SHA256',digest(archive),'bytes',archive.stat().st_size,flush=True)


if __name__=='__main__':
    main()
