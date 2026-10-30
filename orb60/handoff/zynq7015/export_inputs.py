"""Decode verified GRAY8 inputs for PS replay; never resample clocks or rerun ORB."""
import argparse
import hashlib
from pathlib import Path
import av
from common import rows,write_rows,load,sha

def export(bundle,output,selected=None):
    accept=load(bundle/'golden/capture_acceptance.json')
    if sha(bundle/'testdata/video.mp4')!=accept['video_sha256']:raise ValueError('Wrong source recording')
    output.mkdir(parents=True,exist_ok=False);index=[];offset=0
    wanted={int(r['source_frame_index']):r for r in rows(bundle/'golden/frames.csv')
            if selected is None or int(r['frame_index'])==selected}
    if not wanted:raise ValueError('Requested frame does not exist')
    with (output/'gray8.bin.part').open('wb') as binary,av.open(str(bundle/'testdata/video.mp4')) as video:
        for source,frame in enumerate(video.decode(video.streams.video[0])):
            if source not in wanted:continue
            row=wanted[source];data=frame.to_ndarray(format='gray').tobytes()
            if len(data)!=960*720 or hashlib.sha256(data).hexdigest()!=row['gray_sha256']:
                raise ValueError('Decoded grayscale pixels differ at frame'+row['frame_index'])
            binary.write(data);index.append(dict(frame_index=row['frame_index'],source_frame_index=source,
                timestamp_ns=row['timestamp_ns'],byte_offset=offset,bytes=len(data),gray_sha256=row['gray_sha256']))
            offset+=len(data)
    if len(index)!=len(wanted):raise ValueError('Missing source frames')
    (output/'gray8.bin.part').replace(output/'gray8.bin');write_rows(output/'frames.csv',index)
    print('EXPORTED',len(index),'frames',offset,'bytes')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frame',type=int);a=p.parse_args();export(a.bundle,a.output,a.frame)
