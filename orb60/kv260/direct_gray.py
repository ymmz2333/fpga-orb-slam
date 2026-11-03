"""Explicit original-YUV gray plus paired BGR input; never substitute features."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import time
import zlib
import numpy as np

HEADER = struct.Struct('<8sQQII')
MAGIC = b'ORBPAIR1'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):h.update(block)
    return h.hexdigest()


def rows(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))


def pair_header(index, stamp, bgr, gray):
    if type(index) != int or not 0 <= index < 8192 or type(stamp) != int or not 0 < stamp < 2**64:
        raise ValueError('Explicit bounded integer frame identity required')
    if bgr.dtype != np.uint8 or bgr.shape != (720,960,3) or not bgr.flags.c_contiguous:
        raise ValueError('Original contiguous BGR8 required')
    if gray.dtype != np.uint8 or gray.shape != (720,960) or not gray.flags.c_contiguous:
        raise ValueError('Original contiguous GRAY8 required')
    return HEADER.pack(MAGIC,index,stamp,zlib.crc32(memoryview(bgr)),zlib.crc32(memoryview(gray)))


def decoded(video):
    import av
    with av.open(str(video)) as c:
        stream = c.streams.video[0]
        stream.codec_context.thread_type = 'SLICE';stream.codec_context.thread_count = 5
        for i, frame in enumerate(c.decode(stream)):
            if frame.pts is None or frame.time_base is None:raise ValueError('Original integer PTS required')
            stamp = 1000000000 + int(frame.pts * frame.time_base * 1000000000)
            bgr = frame.to_ndarray(format='bgr24');gray = frame.to_ndarray(format='gray')
            header = pair_header(i,stamp,bgr,gray)
            yield i,stamp,bgr,gray,header


def prepare(video, legacy, output, endpoint):
    """Retain all frames; use original physical reference and capture its24-frame prefix."""
    import av
    from .network_frontend import NetworkFrontend
    video,legacy,output = map(Path,(video,legacy,output))
    output.mkdir(parents=True,exist_ok=False)
    source = rows(legacy);byindex = {int(r['source_frame_index']):r for r in source}
    if len(source)!=2273 or sorted(byindex)!=list(range(24,2297)):
        raise ValueError('Expected immutable original source-index reference')
    state = dict(status='RUNNING',scope='Direct gray and paired RGB source provenance; no SLAM/DPU/performance acceptance',
                 video_sha256=digest(video),legacy_csv_sha256=digest(legacy),pyav=av.__version__,
                 decoder='SLICE5',frames=0,legacy_gray_checked=0,legacy_gray_mismatches=[],prefix_physical_frames=0)
    if state['video_sha256']!='c2ab71867980667111e365ea49ddbc618baa8400b3a5723d10652b204f76a7f4':raise ValueError('Wrong original video')
    client = None
    try:
        client = NetworkFrontend(endpoint)
        (output/'prefix_capture').mkdir()
        with (output/'identities.csv').open('w',newline='') as a,(output/'color_identities.csv').open('w',newline='') as b,(output/'reference_features.csv').open('w',newline='') as c:
            ia=csv.writer(a,lineterminator='\n');ib=csv.writer(b,lineterminator='\n');ic=csv.writer(c,lineterminator='\n')
            ia.writerow(['source_frame_id','timestamp_ns','gray_crc']);ib.writerow(['source_frame_id','timestamp_ns','bgr_crc'])
            ic.writerow(['source_frame_id','timestamp_ns','gray_crc','record_crc','count'])
            for i,stamp,bgr,gray,header in decoded(video):
                _,_,_,bc,gc=HEADER.unpack(header)
                ia.writerow([i,stamp,gc]);ib.writerow([i,stamp,bc])
                if i<24:
                    payload,r=client.run(gray,i,stamp)
                    if r['simulated']:raise ValueError('Actual prefix PL required')
                    (output/'prefix_capture'/('%02d.payload'%i)).write_bytes(payload)
                    count=int(r['count']);crc=zlib.crc32(r['records']);state['prefix_physical_frames']+=1
                else:
                    old=byindex[i];state['legacy_gray_checked']+=1
                    if hashlib.sha256(memoryview(gray)).hexdigest()!=old['gray_sha256']:
                        state['legacy_gray_mismatches'].append(i)
                    count=int(old['count']);crc=int(old['record_crc32'])
                ic.writerow([i,stamp,gc,crc,count]);state['frames']=i+1
        if state['frames']!=2297 or state['legacy_gray_checked']!=2273 or state['legacy_gray_mismatches']:
            raise ValueError('Original physical reference gray pixels not reproduced for all frames')
        state.update(status='DIRECT_GRAY_INPUTS_VERIFIED',producer_sha256=digest(__file__),
                     files_sha256={name:digest(output/name) for name in ('identities.csv','color_identities.csv','reference_features.csv')})
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        if client:client.close()
        (output/'SOURCE.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


def validate(proof,video,identities,color_identities,reference=None):
    import av
    value=json.loads(Path(proof).read_text())
    if value.get('status')!='DIRECT_GRAY_INPUTS_VERIFIED' or value.get('pyav')!=av.__version__ or value.get('decoder')!='SLICE5':
        raise ValueError('Original-gray complete source proof required')
    if value.get('video_sha256')!=digest(video) or value.get('producer_sha256')!=digest(__file__):
        raise ValueError('Original-gray source/video changed')
    for name,path in [('identities.csv',identities),('color_identities.csv',color_identities),('reference_features.csv',reference)]:
        if path and value['files_sha256'][name]!=digest(path):raise ValueError('Wrong original-gray manifest: '+name)
    validate_headers(identities,color_identities,reference)
    if value['frames']!=2297 or value['legacy_gray_checked']!=2273 or value['legacy_gray_mismatches'] or value['prefix_physical_frames']!=24:
        raise ValueError('Incomplete original-gray reference scope')
    return value


def validate_headers(identities,color_identities,reference=None):
    for path,header in [(identities,b'source_frame_id,timestamp_ns,gray_crc\n'),
                        (color_identities,b'source_frame_id,timestamp_ns,bgr_crc\n'),
                        (reference,b'source_frame_id,timestamp_ns,gray_crc,record_crc,count\n')]:
        if path:
            with Path(path).open('rb') as f:actual=f.readline()
            if actual!=header:raise ValueError('Native input manifest requires exact LF header: '+str(path))


def stream(video,fifo,identities,color_identities,proof,summary,frames=0):
    validate(proof,video,identities,color_identities)
    path=Path(fifo)
    if not stat.S_ISFIFO(path.lstat().st_mode) or path.stat().st_uid!=os.getuid():raise ValueError('Owned non-symlink FIFO required')
    ids,colors=rows(identities),rows(color_identities)
    if frames<0 or frames>len(ids) or len(ids)!=len(colors):raise ValueError('Invalid source coverage')
    expected=frames or len(ids);count=0;began=time.monotonic_ns()
    report=dict(status='RUNNING',backend='PS_DIRECT_GRAY_PAIRED_BGR_SLICE5',expected_frames=expected,frames=0,proof_sha256=digest(proof))
    try:
        with path.open('wb',buffering=0) as sink:
            for i,stamp,bgr,gray,header in decoded(video):
                if i>=expected:raise ValueError('Extra unindexed source frame')
                _,_,_,bc,gc=HEADER.unpack(header)
                a,b=ids[i],colors[i]
                if (i,stamp,gc)!=(int(a['source_frame_id']),int(a['timestamp_ns']),int(a['gray_crc'])) or (i,stamp,bc)!=(int(b['source_frame_id']),int(b['timestamp_ns']),int(b['bgr_crc'])):
                    raise ValueError('Direct gray/RGB source identity mismatch at%d'%i)
                if i==0 and os.getenv('ORB60_BACKGROUND_CPUS'):
                    from .cpu_policy import pin_current_threads
                    cores=[int(x) for x in os.environ['ORB60_BACKGROUND_CPUS'].split(',')];pin_current_threads(cores)
                    report['affinity_after_codec_initialization']=cores
                for block in (header,memoryview(bgr).cast('B'),memoryview(gray).cast('B')):
                    view=memoryview(block)
                    while view:
                        n=sink.write(view)
                        if not n:raise IOError('Paired video FIFO stopped')
                        view=view[n:]
                count+=1;report['frames']=count
                if frames and count==expected:break
        if count!=expected:raise ValueError('Incomplete paired input drain')
        report['status']='ORIGINAL_VIDEO_FIFO_DRAINED'
    except BaseException as e:report.update(status='FAILED',error=repr(e));raise
    finally:
        report['wall_seconds_including_backpressure']=(time.monotonic_ns()-began)*1e-9
        Path(summary).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare')
    for k in ('video','legacy','output'):a.add_argument('--'+k,type=Path,required=True)
    a.add_argument('--endpoint',required=True)
    a=sub.add_parser('stream')
    for k in ('video','fifo','identities','color_identities','proof','summary'):a.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    a.add_argument('--frames',type=int,default=0)
    args=vars(p.parse_args());action=args.pop('action');globals()[action](**args)
