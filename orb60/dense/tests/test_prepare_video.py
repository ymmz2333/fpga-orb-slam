"""Real codec/PTS/rotation test on an explicitly synthetic 12-frame video."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dense.video import digest,prepare_video

p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
base=a.output/'synthetic.mp4';rotated=a.output/'synthetic_rotated.mp4'
subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=10:duration=1.2',
                '-c:v','mpeg4',str(base)],check=True)
subprocess.run(['ffmpeg','-v','error','-y','-i',str(base),'-c','copy','-metadata:s:v:0','rotate=90',str(rotated)],check=True)
before=digest(rotated)
info=prepare_video(rotated,None,a.output/'dataset',approximate=True)
rows=list(csv.DictReader((a.output/'dataset/frames.csv').open()))
assert len(rows)==12
assert [int(r['source_frame_index']) for r in rows]==list(range(12))
assert [int(r['original_pts_ns']) for r in rows]==[i*100000000 for i in range(12)]
assert info['rotation_degrees']%180==90 and info['roi']==[210,0,540,720]
mask=cv2.imread(str(a.output/'dataset/valid_mask.png'),cv2.IMREAD_GRAYSCALE)
assert mask.shape==(720,960) and not mask[:,:210].any() and mask[:,210:750].all()
f=cv2.FileStorage(str(a.output/'dataset/camera.yaml'),cv2.FILE_STORAGE_READ)
assert all(f.getNode('Camera1.'+name).isReal() for name in ['fx','fy','cx','cy'])
f.release()
assert digest(rotated)==before
report=dict(status='PASS',synthetic_fixture=True,frames=12,source_pts_preserved=True,
            rotation=info['rotation_degrees'],roi=info['roi'],real_yaml_intrinsics=True,source_unchanged=True)
(a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
