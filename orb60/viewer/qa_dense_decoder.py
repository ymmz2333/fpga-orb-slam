"""Compare fresh-decoder seeking to exact sequential decoding of the real video."""
import argparse
import json
from pathlib import Path
import time
import cv2
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--video',required=True,type=Path)
    p.add_argument('--result',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();r=json.loads((a.result/'map_0/replay.json').read_text())
    frames=r['frames'];keys=[f for f in frames if 'keyframe_id' in f]
    targets={f['source_frame_index'] for f in [keys[0],keys[len(keys)//3],keys[-1],frames[-1]]}
    cap=cv2.VideoCapture(str(a.video));expected={};start=time.perf_counter()
    for index in range(max(targets)+1):
        ok,image=cap.read();assert ok,index
        if index in targets:expected[index]=image
    cap.release();reports=[]
    for index in sorted(targets,reverse=True):
        clock=time.perf_counter();cap=cv2.VideoCapture(str(a.video))
        assert cap.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,image=cap.read();assert ok,index
        assert int(round(cap.get(cv2.CAP_PROP_POS_FRAMES)))==index+1
        cap.release();np.testing.assert_array_equal(image,expected[index])
        reports.append(dict(source_frame=index,seek_seconds=time.perf_counter()-clock,sequential_pixels_exact=True))
    report=dict(status='PASS',frames=reports,total_seconds=time.perf_counter()-start)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
