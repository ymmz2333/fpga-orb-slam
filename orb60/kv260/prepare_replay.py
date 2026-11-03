"""Package a bounded subset of the frozen physical capture for native PS tests."""
import argparse,csv,hashlib,json,shutil
from pathlib import Path
import cv2
from .camera_contract import from_yaml

ROOT=Path(__file__).resolve().parents[2]


def prepare(output,frames):
    if output.exists():raise ValueError('Fresh replay directory required')
    source=ROOT/'orb60/build/handoff/zynq7015_20261022';gold=source/'golden'
    acceptance=json.loads((gold/'capture_acceptance.json').read_text())
    if acceptance['status']!='PASS' or acceptance['cpu_orb_calls']!=0:raise ValueError('Physical capture not accepted')
    for path,key in [(gold/'features.bin','features_sha256'),(gold/'runtime.bin','runtime_sha256'),(source/'testdata/video.mp4','video_sha256')]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=acceptance[key]:raise ValueError('Frozen input changed: '+str(path))
    with (gold/'frames.csv').open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))[:frames]
    if len(rows)!=frames or any(int(row['frame_index'])!=i for i,row in enumerate(rows)):raise ValueError('Noncontiguous capture')
    output.mkdir(parents=True);capture=output/'capture';capture.mkdir()
    with (capture/'frames.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    end=max((int(row['record_offset'])+int(row['count']))*64 for row in rows)
    (capture/'features.bin').write_bytes((gold/'features.bin').read_bytes()[:end])
    (capture/'runtime.bin').write_bytes((gold/'runtime.bin').read_bytes()[:frames*1152])
    shutil.copy2(source/'testdata/video.mp4',output/'video.mp4')
    camera=ROOT/'rk3588/orbslam3_cpu_baseline/configs/c/tello_oafd_960x720_provisional.yaml'
    shutil.copy2(camera,output/'camera.yaml')
    (output/'camera.csv').write_bytes(from_yaml(camera))
    (output/'PROVENANCE.json').write_text(json.dumps(dict(backend='saved_physical_7015_PL',live_kv260_pl=False,frames=frames,calibration='retained provisional intrinsics; not a calibration accuracy test',source_acceptance=acceptance),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--frames',type=int,default=300);a=p.parse_args();prepare(a.output,a.frames)
