"""FRAME5 decoding with explicit compressed-source repairs of both pixel planes."""
import argparse
import json
import os
from pathlib import Path
import stat
import time
import numpy as np
import av
from .direct_gray import digest,rows,pair_header,HEADER,validate,decoded


def regions(indices):
    return 0 if not indices else 1+sum(b!=a+1 for a,b in zip(indices,indices[1:]))


def validate_indices(indices,count):
    if (not isinstance(indices,list) or any(type(i)!=int for i in indices) or indices!=sorted(set(indices))
        or len(indices)>64 or len(indices)>count*.05 or regions(indices)>4
        or (indices and (indices[0]<0 or indices[-1]>=count))):
        raise ValueError('Paired repair set exceeds explicit bounded scope')


def context(video,identities,color_identities,proof):
    source=validate(proof,video,identities,color_identities)
    return dict(video_sha256=source['video_sha256'],identities_sha256=digest(identities),
                color_identities_sha256=digest(color_identities),source_proof_sha256=digest(proof),
                decoder_source_sha256=digest(__file__),pyav=av.__version__,frames=source['frames'])


def diagnose(video,identities,color_identities,proof,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    c=context(video,identities,color_identities,proof);a,b=rows(identities),rows(color_identities)
    state=dict(status='RUNNING',**c,mismatches=[],decoded=0,scope='FRAME-only source diagnostic; no DPU, SLAM or whole-system performance claim')
    try:
        with av.open(str(video)) as container:
            stream=container.streams.video[0];stream.codec_context.thread_type='FRAME';stream.codec_context.thread_count=5
            for i,frame in enumerate(container.decode(stream)):
                if i>=len(a):raise ValueError('Extra diagnostic frame')
                stamp=1000000000+int(frame.pts*frame.time_base*1000000000)
                bgr=frame.to_ndarray(format='bgr24');gray=frame.to_ndarray(format='gray')
                _,index,ts,bc,gc=HEADER.unpack(pair_header(i,stamp,bgr,gray))
                if (index,ts)!=(int(a[i]['source_frame_id']),int(a[i]['timestamp_ns'])) or (index,ts)!=(int(b[i]['source_frame_id']),int(b[i]['timestamp_ns'])):
                    raise ValueError('Diagnostic integer source identity mismatch')
                bad_g=gc!=int(a[i]['gray_crc']);bad_b=bc!=int(b[i]['bgr_crc'])
                if bad_g or bad_b:state['mismatches'].append(dict(source_frame_id=i,gray=bad_g,bgr=bad_b))
                state['decoded']=i+1
        if state['decoded']!=len(a):raise ValueError('Incomplete source diagnostic')
        state['status']='FAILED_SOURCE_PIXELS' if state['mismatches'] else 'FRAME_PAIR_PIXELS_MATCH'
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:(output/'DIAGNOSTIC.json').write_text(json.dumps(state,indent=2)+'\n')
    indices=[r['source_frame_id'] for r in state['mismatches']];validate_indices(indices,len(a))
    plan=dict(format='PAIRED_GRAY_BGR_REPAIR_V1',status='UNVERIFIED_REPAIR_PLAN',**c,indices=indices,regions=regions(indices),
              diagnostic_sha256=digest(output/'DIAGNOSTIC.json'),semantics='Fresh SLICE5 decoding only at explicit indices; both planes must pass independent full pixel comparison')
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],frames=state['decoded'],mismatches=len(indices),regions=regions(indices))),flush=True)
    return 2 if indices else 0


class ExactPairedDecoder:
    def __init__(self,video,identities,color_identities,proof,plan):
        self.video=Path(video);self.plan_path=Path(plan);self.plan=json.loads(self.plan_path.read_text());p=self.plan
        c=context(video,identities,color_identities,proof)
        if p.get('format')!='PAIRED_GRAY_BGR_REPAIR_V1' or any(p.get(k)!=v for k,v in c.items()):raise ValueError('Paired decoder plan source/config mismatch')
        validate_indices(p['indices'],c['frames']);self.allowed=set(p['indices']);self.ids=rows(identities);self.colors=rows(color_identities)
        if len(self.ids)!=len(self.colors):raise ValueError('Incomplete paired manifests')
        self.container=av.open(str(video));self.stream=self.container.streams.video[0]
        self.stream.codec_context.thread_type='FRAME';self.stream.codec_context.thread_count=5
        self.frames=iter(self.container.decode(self.stream));self.slice_container=None;self.slice_frames=None;self.slice_last=-2
        self.report=dict(status='RUNNING',frames=0,expected_frames=c['frames'],repaired=[],repair_windows=[],plan_sha256=digest(plan),**{k:v for k,v in c.items() if k!='frames'})

    def close_slice(self):
        if self.slice_container is not None:self.slice_container.close()
        self.slice_container=None;self.slice_frames=None;self.slice_last=-2

    def repair(self,index,target,stamp):
        if self.slice_container is None or index!=self.slice_last+1:
            self.close_slice();self.slice_container=av.open(str(self.video));stream=self.slice_container.streams.video[0]
            stream.codec_context.thread_type='SLICE';stream.codec_context.thread_count=5
            self.slice_container.seek(target.pts,stream=stream,backward=True,any_frame=False)
            self.slice_frames=iter(self.slice_container.decode(stream));self.report['repair_windows'].append(dict(first_source_frame=index,decoded=0,elapsed_ns=0))
        window=self.report['repair_windows'][-1];began=time.monotonic_ns()
        for frame in self.slice_frames:
            window['decoded']+=1
            if window['decoded']>300:raise ValueError('Paired compressed-source repair exceeded300 frames')
            actual=1000000000+int(frame.pts*frame.time_base*1000000000)
            if actual>stamp:raise ValueError('Repair skipped required integer source PTS')
            if actual==stamp:
                self.slice_last=index;window['elapsed_ns']+=time.monotonic_ns()-began;return frame
        raise ValueError('Repair source ended before required frame')

    def read(self):
        try:frame=next(self.frames)
        except StopIteration:
            if self.report['frames']!=len(self.ids):raise ValueError('Incomplete paired decode')
            if self.report['repaired']!=self.plan['indices']:raise ValueError('Incomplete explicit repair coverage')
            self.report['status']='EXACT_PAIRED_FRAME_REPAIR_DRAINED';return None
        i=self.report['frames']
        if i>=len(self.ids):raise ValueError('Extra paired source frame')
        stamp=1000000000+int(frame.pts*frame.time_base*1000000000);a,b=self.ids[i],self.colors[i]
        if (i,stamp)!=(int(a['source_frame_id']),int(a['timestamp_ns'])) or (i,stamp)!=(int(b['source_frame_id']),int(b['timestamp_ns'])):raise ValueError('Paired decoder integer PTS/order mismatch')
        if i in self.allowed:
            frame=self.repair(i,frame,stamp);self.report['repaired'].append(i)
        else:self.close_slice()
        bgr=frame.to_ndarray(format='bgr24');gray=frame.to_ndarray(format='gray');header=pair_header(i,stamp,bgr,gray)
        _,_,_,bc,gc=HEADER.unpack(header)
        if gc!=int(a['gray_crc']) or bc!=int(b['bgr_crc']):raise ValueError('Unapproved paired source pixels at frame%d'%i)
        self.report['frames']=i+1
        return i,stamp,bgr,gray,header

    def close(self):self.close_slice();self.container.close()


def gate(video,identities,color_identities,proof,plan,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);c=context(video,identities,color_identities,proof)
    state=dict(status='RUNNING',**c,plan_sha256=digest(plan),compared_frames=0,gray_pixel_mismatches=0,bgr_pixel_mismatches=0,
               scope='Fresh independent SLICE5 and repaired FRAME5 arrays compared per pixel in both planes; no whole-system FPS claim')
    decoder=None;reference=None
    try:
        decoder=ExactPairedDecoder(video,identities,color_identities,proof,plan);reference=decoded(video)
        for expected in reference:
            actual=decoder.read()
            if actual is None or actual[:2]!=expected[:2]:raise ValueError('Incomplete paired reference association')
            if not np.array_equal(actual[2],expected[2]):state['bgr_pixel_mismatches']+=1
            if not np.array_equal(actual[3],expected[3]):state['gray_pixel_mismatches']+=1
            state['compared_frames']+=1
        if decoder.read() is not None or state['compared_frames']!=c['frames'] or state['gray_pixel_mismatches'] or state['bgr_pixel_mismatches']:raise ValueError('Full exact paired pixel gate failed')
        state.update(status='EXACT_PAIRED_FRAME_REPAIR_PIXEL_PASS',decoder=decoder.report)
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        if decoder:decoder.close()
        if reference:reference.close()
        (output/'PROOF.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(dict(status=state['status'],frames=state['compared_frames'],repairs=len(state['decoder']['repaired']))),flush=True)


def validate_proof(decoder_proof,video,identities,color_identities,proof,plan):
    d=json.loads(Path(decoder_proof).read_text());c=context(video,identities,color_identities,proof)
    if d.get('status')!='EXACT_PAIRED_FRAME_REPAIR_PIXEL_PASS' or any(d.get(k)!=v for k,v in c.items()) or d.get('plan_sha256')!=digest(plan):raise ValueError('Exact paired decoder full pixel proof mismatch')
    p=json.loads(Path(plan).read_text());validate_indices(p['indices'],c['frames'])
    if d['compared_frames']!=c['frames'] or d['gray_pixel_mismatches'] or d['bgr_pixel_mismatches'] or d['decoder']['repaired']!=p['indices'] or d['decoder']['status']!='EXACT_PAIRED_FRAME_REPAIR_DRAINED':raise ValueError('Incomplete paired source proof')
    return d


def stream(video,fifo,identities,color_identities,proof,plan,decoder_proof,summary,frames=0):
    validate_proof(decoder_proof,video,identities,color_identities,proof,plan)
    path=Path(fifo);ids=rows(identities)
    if not stat.S_ISFIFO(path.lstat().st_mode) or path.stat().st_uid!=os.getuid() or frames<0 or frames>len(ids):raise ValueError('Owned FIFO and bounded frame coverage required')
    expected=frames or len(ids);decoder=None;began=time.monotonic_ns()
    state=dict(status='RUNNING',backend='PS_EXACT_PAIRED_FRAME5_SLICE5_REPAIR',frames=0,expected_frames=expected,decoder_proof_sha256=digest(decoder_proof))
    try:
        with path.open('wb',buffering=0) as sink:
            decoder=ExactPairedDecoder(video,identities,color_identities,proof,plan)
            for i in range(expected):
                item=decoder.read()
                if item is None:raise ValueError('Paired decoder ended early')
                _,_,bgr,gray,header=item
                if i==0 and os.getenv('ORB60_BACKGROUND_CPUS'):
                    from .cpu_policy import pin_current_threads
                    cores=[int(x) for x in os.environ['ORB60_BACKGROUND_CPUS'].split(',')];pin_current_threads(cores);state['affinity_after_codec_initialization']=cores
                for block in (header,memoryview(bgr).cast('B'),memoryview(gray).cast('B')):
                    view=memoryview(block)
                    while view:
                        n=sink.write(view)
                        if not n:raise IOError('Paired FIFO stopped')
                        view=view[n:]
                state['frames']=i+1
            if not frames and decoder.read() is not None:raise ValueError('Extra paired source frame')
        state['status']='ORIGINAL_VIDEO_FIFO_DRAINED'
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        if decoder:state['decoder']=decoder.report;decoder.close()
        state['wall_seconds_including_backpressure']=(time.monotonic_ns()-began)*1e-9
        Path(summary).write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    for action in ('diagnose','gate','stream'):
        a=sub.add_parser(action)
        for key in ('video','identities','color_identities','proof'):a.add_argument('--'+key.replace('_','-'),type=Path,required=True)
        for key in (() if action=='diagnose' else ('plan',)):a.add_argument('--'+key,type=Path,required=True)
        if action=='stream':
            for key in ('fifo','decoder_proof','summary'):a.add_argument('--'+key.replace('_','-'),type=Path,required=True)
            a.add_argument('--frames',type=int,default=0)
        else:a.add_argument('--output',type=Path,required=True)
    args=vars(p.parse_args());action=args.pop('action');result=globals()[action](**args)
    raise SystemExit(result or 0)
