"""Freeze exact original-video integer PTS and independently decoded gray CRC."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import zlib
import cv2


def prepare(video,output):
    import av
    video=Path(video);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    hashes=hashlib.sha256()
    with video.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):hashes.update(block)
    count=0;previous=-1
    with av.open(str(video)) as container,(output/'identities.csv').open('w',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(['source_frame_id','timestamp_ns','gray_crc'])
        for frame in container.decode(video=0):
            if frame.pts is None or frame.time_base is None:raise ValueError('Video input has no original PTS')
            stamp=1000000000+int(frame.pts*frame.time_base*1000000000)
            bgr=frame.to_ndarray(format='bgr24')
            if bgr.shape!=(720,960,3) or stamp<=previous:raise ValueError('Explicit 960x720 video and monotonic original PTS required')
            gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
            writer.writerow([count,stamp,zlib.crc32(gray.tobytes())]);previous=stamp;count+=1
    if count<2:raise ValueError('Insufficient original input frames')
    record=dict(status='SOURCE_VIDEO_IDENTITIES_FROZEN',frames=count,video_sha256=hashes.hexdigest(),
                original_pts_integer=True,gray='PyAV BGR24 plus OpenCV BGR2GRAY, unchanged working pixels',
                identities_sha256=hashlib.sha256((output/'identities.csv').read_bytes()).hexdigest())
    (output/'SOURCE.json').write_text(json.dumps(record,indent=2)+'\n');return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.video,a.output)))
