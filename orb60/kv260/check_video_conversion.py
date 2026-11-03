"""Paired real-video conversion check; not a full-system throughput test."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import time
import zlib
import av
import cv2
import numpy as np
from .video_conversion import BgrConverter
from .run_network_system import digest


def check(video,identities,output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh conversion report required')
    cv2.setNumThreads(1)
    with Path(identities).open(newline='') as f:rows=list(csv.DictReader(f))
    ref=BgrConverter(False);cached=BgrConverter(True);times=[[],[]];count=0
    state=dict(status='RUNNING',scope='PS conversion-only paired test, not DPU or whole-system FPS',
               av_version=av.__version__,video_sha256=digest(video),identities_sha256=digest(identities))
    try:
        with av.open(str(video)) as container:
            stream=container.streams.video[0]
            for i,frame in enumerate(container.decode(stream)):
                if i>=len(rows):raise ValueError('Extra video input')
                if i==0:state.update(resolved_threads=stream.codec_context.thread_count,thread_type=str(stream.codec_context.thread_type))
                result={}
                for choice in ([0,1] if i%2 else [1,0]):
                    start=time.perf_counter_ns();result[choice]=(cached if choice else ref).convert(frame)
                    times[choice].append((time.perf_counter_ns()-start)*1e-6)
                if not np.array_equal(result[0],result[1]):raise ValueError('Color pixels differ at source frame%d'%i)
                stamp=1000000000+int(frame.pts*frame.time_base*1000000000);crc=zlib.crc32(cv2.cvtColor(result[1],cv2.COLOR_BGR2GRAY).tobytes())
                r=rows[i]
                if (i,stamp,crc)!=(int(r['source_frame_id']),int(r['timestamp_ns']),int(r['gray_crc'])):
                    raise ValueError('Frozen source differs at source frame%d'%i)
                count=i+1
                if count%300==0:print('CONVERSION_CHECK',count,flush=True)
        if not count or count!=len(rows):raise ValueError('Incomplete video drain')
        state.update(status='EXACT_PERSISTENT_BGR_CONVERSION_PASS',frames=count,color_mismatches=0,frozen_identity_mismatches=0,
                     median_ms={'reference':statistics.median(times[0]),'persistent':statistics.median(times[1])},
                     mean_ms={'reference':statistics.mean(times[0]),'persistent':statistics.mean(times[1])})
    except BaseException as error:state.update(status='FAILED',error=repr(error));raise
    finally:output.write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True);return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('video','identities','output'):p.add_argument('--'+name,type=Path,required=True)
    check(**vars(p.parse_args()))
