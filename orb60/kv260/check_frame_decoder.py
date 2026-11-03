"""Explicit alternate PS decoder diagnostic; never relabel pixel differences PASS."""
import argparse
import csv
import json
from pathlib import Path
import time
import zlib
import av
import cv2
from .run_network_system import digest


def check(video,identities,output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh diagnostic report required')
    cv2.setNumThreads(1)
    with Path(identities).open(newline='') as f:rows=list(csv.DictReader(f))
    report=dict(status='RUNNING',scope='PS alternate decoder only, no DPU or whole FPS acceptance',
                threads=5,thread_type='FRAME',frames=0,pixel_mismatches=[],video_sha256=digest(video),identities_sha256=digest(identities))
    start=time.monotonic_ns()
    try:
        with av.open(str(video)) as container:
            stream=container.streams.video[0];stream.codec_context.thread_type='FRAME';stream.codec_context.thread_count=5
            for i,frame in enumerate(container.decode(stream)):
                if i>=len(rows):raise ValueError('Extra input frame')
                stamp=1000000000+int(frame.pts*frame.time_base*1000000000);row=rows[i]
                if (int(row['source_frame_id']),int(row['timestamp_ns']))!=(i,stamp):raise ValueError('Alternate timestamp/order differs')
                bgr=frame.to_ndarray(format='bgr24')
                if bgr.shape!=(720,960,3):raise ValueError('Incorrect original dimensions')
                crc=zlib.crc32(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY).tobytes())
                if crc!=int(row['gray_crc']):report['pixel_mismatches'].append(dict(source_frame_id=i,timestamp_ns=stamp,actual_gray_crc=crc,expected_gray_crc=int(row['gray_crc'])))
                report['frames']=i+1
                if (i+1)%300==0:print('FRAME_DECODER_DIAGNOSTIC',i+1,flush=True)
        if report['frames']!=len(rows):raise ValueError('Incomplete input')
        report.update(status='EXACT_FRAME_DECODER_COMPONENT_PASS' if not report['pixel_mismatches'] else 'FAILED_SOURCE_PIXELS',
                      elapsed_seconds=(time.monotonic_ns()-start)*1e-9)
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('video','identities','output'):p.add_argument('--'+name,type=Path,required=True)
    result=check(**vars(p.parse_args()));raise SystemExit(0 if result['status']=='EXACT_FRAME_DECODER_COMPONENT_PASS' else 2)
