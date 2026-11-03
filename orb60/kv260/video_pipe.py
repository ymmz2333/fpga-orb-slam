"""Explicit retained PyAV decoder feeding a bounded FIFO; no pixel changes."""
import argparse
import csv
import json
import hashlib
import os
from pathlib import Path
import stat
import time


def stream_repaired(video,fifo,identities,summary,frames=0):
    from .frame_decoder import ExactFrameDecoder,validate_proof
    plan=os.environ['ORB60_VIDEO_REPAIR_PLAN'];proof=os.getenv('ORB60_VIDEO_REPAIR_PROOF')
    if not proof:raise ValueError('Paired full-color proof required for production repaired decoder')
    gate=validate_proof(proof,video,identities,plan)
    path=Path(fifo)
    if not stat.S_ISFIFO(path.lstat().st_mode) or path.stat().st_uid!=os.getuid():raise ValueError('Owned non-symlink FIFO required')
    with Path(identities).open(newline='') as f:rows=list(csv.DictReader(f))
    if frames<0 or frames>len(rows) or gate['frames']!=len(rows) or gate['decoder']['status']!='EXACT_FRAME_REPAIR_DRAINED':
        raise ValueError('Incomplete decoder proof or invalid bounded input')
    if gate['decoder']['repaired']!=json.loads(Path(plan).read_text())['indices']:raise ValueError('Incomplete verified repair set')
    expected=frames or len(rows);decoder=None;began=time.monotonic_ns()
    report=dict(status='RUNNING',backend='PS_FRAME5_EXPLICIT_SLICE5_REPAIR',frames=0,expected_frames=expected,
                acceptance_proof_sha256=hashlib.sha256(Path(proof).read_bytes()).hexdigest())
    try:
        with path.open('wb',buffering=0) as sink:
            decoder=ExactFrameDecoder(video,identities,plan)
            for i in range(expected):
                ok,bgr=decoder.read()
                if not ok:raise ValueError('Repaired decoder source ended early')
                if i==0:
                    report.update(resolved_decoder_threads=decoder.stream.codec_context.thread_count,decoder_thread_type=str(decoder.stream.codec_context.thread_type))
                    if os.getenv('ORB60_BACKGROUND_CPUS'):
                        from .cpu_policy import pin_current_threads
                        cores=[int(x) for x in os.environ['ORB60_BACKGROUND_CPUS'].split(',')]
                        pin_current_threads(cores);report['affinity_after_codec_initialization']=cores
                view=memoryview(bgr).cast('B')
                while view:
                    written=sink.write(view)
                    if not written:raise IOError('Repaired decoder FIFO stopped')
                    view=view[written:]
                report['frames']=i+1
            if not frames and decoder.read()[0]:raise ValueError('Extra repaired video frame')
        report['status']='ORIGINAL_VIDEO_FIFO_DRAINED'
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        if decoder:report['decoder']=decoder.report;decoder.close()
        report['wall_seconds_including_backpressure']=(time.monotonic_ns()-began)*1e-9
        Path(summary).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


def stream(video,fifo,identities,summary,frames=0):
    if os.getenv('ORB60_VIDEO_REPAIR_PLAN'):return stream_repaired(video,fifo,identities,summary,frames)
    if os.getenv('ORB60_VIDEO_REPAIR_PROOF'):raise ValueError('Repair proof without explicit plan')
    import av
    path=Path(fifo)
    if not stat.S_ISFIFO(path.lstat().st_mode) or path.stat().st_uid!=os.getuid():
        raise ValueError('Owned, non-symlink FIFO required')
    with Path(identities).open(newline='') as f:rows=list(csv.DictReader(f))
    if frames:rows=rows[:frames]
    if not rows:raise ValueError('Frozen input identities required')
    report=dict(status='RUNNING',backend='retained_PyAV_BGR24',frames=0,expected_frames=len(rows))
    from .video_conversion import BgrConverter
    reuse=os.getenv('ORB60_DECODER_REUSE_CONVERTER')=='1';converter=BgrConverter(reuse)
    report['persistent_bgr_converter']=reuse
    began=time.monotonic()
    try:
        with path.open('wb',buffering=0) as sink,av.open(str(video)) as container:
            stream=container.streams.video[0]
            # Preserve the exact reference decoder configuration, including its
            # treatment of damaged H.264 slices. Changing thread_count changes
            # concealed pixels in the supplied video around source frame974.
            for frame in container.decode(stream):
                i=report['frames']
                if i==0:
                    report['resolved_decoder_threads']=stream.codec_context.thread_count
                    report['decoder_thread_type']=str(stream.codec_context.thread_type)
                    # Let FFmpeg initialize with the original visible CPU count
                    # before moving its existing threads. Thread-count changes
                    # alter concealment of the damaged source slice at974.
                    if os.getenv('ORB60_BACKGROUND_CPUS'):
                        from .cpu_policy import pin_current_threads
                        cores=[int(x) for x in os.environ['ORB60_BACKGROUND_CPUS'].split(',')]
                        pin_current_threads(cores);report['affinity_after_codec_initialization']=cores
                if i>=len(rows):raise ValueError('Extra decoded source frames')
                stamp=1000000000+int(frame.pts*frame.time_base*1000000000)
                if int(rows[i]['source_frame_id'])!=i or int(rows[i]['timestamp_ns'])!=stamp:
                    raise ValueError('Decoder source integer timestamp differs from frozen input')
                bgr=converter.convert(frame)
                if bgr.shape!=(720,960,3):raise ValueError('Explicit 960x720 original video required')
                view=memoryview(bgr).cast('B')
                while view:
                    written=sink.write(view)
                    if not written:raise IOError('Decoder FIFO stopped')
                    view=view[written:]
                report['frames']+=1
                if frames and report['frames']==frames:break
        if report['frames']!=len(rows):raise ValueError('Decoder did not drain all frozen source frames')
        report['status']='ORIGINAL_VIDEO_FIFO_DRAINED'
    except BaseException as error:report.update(status='FAILED',error=repr(error));raise
    finally:
        report['wall_seconds_including_backpressure']=time.monotonic()-began
        Path(summary).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('video','fifo','identities','summary'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--frames',type=int,default=0)
    a=p.parse_args();stream(a.video,a.fifo,a.identities,a.summary,a.frames)
