"""Audit generated gray PNGs; reconstruct corrupt files from the paired original MP4."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import cv2
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    rows=list(csv.DictReader((a.dataset/'frames.csv').open()));bad=[]
    for row in rows:
        path=a.dataset/'mav0/cam0/data'/(row['timestamp_ns']+'.png')
        im=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        if im is None or im.shape!=(720,960) or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:bad.append(row)
    cap=subprocess.Popen(['ffmpeg','-v','error','-threads','2','-i',str(a.video),'-vsync','0','-f','rawvideo','-pix_fmt','gray','-'],stdout=subprocess.PIPE)
    cursor=0;repaired=[]
    # Check neighboring valid frames first, so an incorrect preprocessing assumption
    # cannot silently change a generated input. Original MP4 is never modified.
    checks=set()
    for row in bad:
        pos=rows.index(row)
        checks.update(i for i in (pos-1,pos+1) if 0<=i<len(rows) and rows[i] not in bad)
    targets={int(rows[i]['source_frame_index']):('check',rows[i]) for i in checks}
    targets.update({int(r['source_frame_index']):('repair',r) for r in bad})
    decoded={}
    try:
        for index,(kind,row) in sorted(targets.items()):
            while cursor<=index:
                raw=cap.stdout.read(720*960)
                if len(raw)!=720*960:raise RuntimeError('Original source ended before requested frame')
                cursor+=1
            gray=np.frombuffer(raw,np.uint8).reshape(720,960)
            path=a.dataset/'mav0/cam0/data'/(row['timestamp_ns']+'.png')
            if kind=='check':
                if not np.array_equal(gray,cv2.imread(str(path),0)):raise RuntimeError('Original/prepared grayscale mismatch: '+str(path))
            else:decoded[index]=(path,gray)
        for index,(path,gray) in decoded.items():
            if path.exists():shutil.copy2(str(path),str(a.output/(path.name+'.corrupt')))
            tmp=path.with_name(path.stem+'.repair.png')
            if not cv2.imwrite(str(tmp),gray,[cv2.IMWRITE_PNG_COMPRESSION,3]) or not np.array_equal(cv2.imread(str(tmp),0),gray):raise RuntimeError('Repair verification failed')
            if hashlib.sha256(tmp.read_bytes()).hexdigest()!=next(r['sha256'] for r in bad if r['timestamp_ns']==path.stem):
                raise RuntimeError('Repaired PNG differs from original SHA256 manifest')
            tmp.replace(path);repaired.append(dict(source_frame_index=index,file=path.name,gray_sha256=hashlib.sha256(gray.tobytes()).hexdigest()))
    finally:
        cap.stdout.close();cap.terminate();cap.wait(timeout=10)
    report=dict(status='PASS',audited=len(rows),repaired=repaired,neighbor_pixel_checks=len(checks),original_read_only=True)
    (a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
