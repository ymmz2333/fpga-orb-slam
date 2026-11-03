"""PS FRAME decoding with explicit source-checked SLICE repair windows.

The original failed FRAME-only check stays failed. Selected video frames are
decoded again from compressed packets using the retained SLICE configuration;
no saved pixels, saved features, frame skipping or changed CRC gates.
"""
import csv
import json
from pathlib import Path
import time
import zlib
import av
import cv2
from .run_network_system import digest


def prepare_plan(diagnostic,output,pyav_version):
    diagnostic,output=Path(diagnostic),Path(output)
    if output.exists():raise ValueError('Fresh repair plan required')
    d=json.loads(diagnostic.read_text());indices=[int(x['source_frame_id']) for x in d['pixel_mismatches']]
    if d['status']!='FAILED_SOURCE_PIXELS' or d['thread_type']!='FRAME' or d['threads']!=5 or indices!=sorted(set(indices)):
        raise ValueError('Expected preserved failed FRAME diagnostic')
    regions=1+sum(b!=a+1 for a,b in zip(indices,indices[1:])) if indices else 0
    if not 0<len(indices)<=64 or regions>4 or len(indices)>d['frames']*.05 or min(indices)<0 or max(indices)>=d['frames']:
        raise ValueError('Repair plan exceeds bounded scope')
    plan=dict(format='EXACT_VIDEO_REPAIR_V1',status='REPAIR_PLAN_UNVERIFIED',video_sha256=d['video_sha256'],
              identities_sha256=d['identities_sha256'],frames=d['frames'],indices=indices,regions=regions,
              threads=5,pyav_version=pyav_version,diagnostic_sha256=digest(diagnostic),
              semantics='Fresh compressed-source SLICE decoding of explicit frame indices; independent full color gate required')
    output.write_text(json.dumps(plan,indent=2)+'\n');return plan


class ExactFrameDecoder:
    def __init__(self,video,identities,plan_path):
        self.video=Path(video);self.plan_path=Path(plan_path);self.plan=json.loads(self.plan_path.read_text())
        p=self.plan
        if p.get('format')!='EXACT_VIDEO_REPAIR_V1' or p.get('threads')!=5 or p.get('pyav_version')!=av.__version__:
            raise ValueError('Repair plan decoder/version mismatch')
        if digest(self.video)!=p['video_sha256'] or digest(identities)!=p['identities_sha256']:
            raise ValueError('Repair plan belongs to another video/identity set')
        with Path(identities).open(newline='') as f:self.rows=list(csv.DictReader(f))
        self.allowed=set(p['indices'])
        if p['indices']!=sorted(self.allowed) or len(self.rows)!=p['frames'] or not self.allowed or len(self.allowed)>64 or len(self.allowed)>len(self.rows)*.05:
            raise ValueError('Unbounded/invalid repair frame list')
        if min(self.allowed)<0 or max(self.allowed)>=len(self.rows) or 1+sum(b!=a+1 for a,b in zip(p['indices'],p['indices'][1:]))>4:
            raise ValueError('Invalid repair windows')
        self.container=av.open(str(video));self.stream=self.container.streams.video[0]
        self.stream.codec_context.thread_type='FRAME';self.stream.codec_context.thread_count=5
        self.frames=iter(self.container.decode(self.stream));self.slice_container=None;self.slice_frames=None;self.slice_last=-2
        self.started=time.monotonic_ns();self.timestamp_ns=None;self.report=dict(status='RUNNING',backend='PS_FRAME5_EXPLICIT_SLICE5_REPAIR',frames=0,
             plan_sha256=digest(plan_path),decoder_source_sha256=digest(__file__),pyav_version=av.__version__,repaired=[],repair_windows=[])

    def repair(self,index,target):
        if self.slice_container is None or index!=self.slice_last+1:
            self.close_slice();self.slice_container=av.open(str(self.video));stream=self.slice_container.streams.video[0]
            stream.codec_context.thread_type='SLICE';stream.codec_context.thread_count=5
            self.slice_container.seek(target.pts,stream=stream,backward=True,any_frame=False)
            self.slice_frames=iter(self.slice_container.decode(stream))
            self.report['repair_windows'].append(dict(first_source_frame=index,decoded=0,elapsed_ns=0))
        window=self.report['repair_windows'][-1];began=time.monotonic_ns()
        for frame in self.slice_frames:
            window['decoded']+=1
            if window['decoded']>300:raise ValueError('Repair seek window exceeded300 frames')
            stamp=1000000000+int(frame.pts*frame.time_base*1000000000)
            if stamp>self.timestamp_ns:raise ValueError('Repair seek skipped the required original timestamp')
            if stamp==self.timestamp_ns:
                self.slice_last=index;window['elapsed_ns']+=time.monotonic_ns()-began
                return frame.to_ndarray(format='bgr24')
        raise ValueError('Repair source ended before the required frame')

    def read(self):
        try:frame=next(self.frames)
        except StopIteration:
            if self.report['frames']!=len(self.rows):raise ValueError('Incomplete parallel decoder input')
            self.report.update(status='EXACT_FRAME_REPAIR_DRAINED',elapsed_ns=time.monotonic_ns()-self.started)
            return False,None
        i=self.report['frames']
        if i>=len(self.rows):raise ValueError('Extra parallel decoder frame')
        self.timestamp_ns=1000000000+int(frame.pts*frame.time_base*1000000000);row=self.rows[i]
        if (i,self.timestamp_ns)!=(int(row['source_frame_id']),int(row['timestamp_ns'])):raise ValueError('Parallel decoder timestamp/order mismatch')
        if i in self.allowed:
            bgr=self.repair(i,frame);self.report['repaired'].append(i)
        else:
            self.close_slice();bgr=frame.to_ndarray(format='bgr24')
        if bgr.shape!=(720,960,3) or zlib.crc32(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY).tobytes())!=int(row['gray_crc']):
            raise ValueError('Reconstructed source pixels differ at frame%d'%i)
        self.report['frames']=i+1
        return True,bgr

    def close_slice(self):
        if self.slice_container is not None:self.slice_container.close()
        self.slice_container=None;self.slice_frames=None;self.slice_last=-2

    def close(self):
        self.close_slice();self.container.close()


def validate_proof(proof,video,identities,plan):
    d=json.loads(Path(proof).read_text())
    expected={'video_sha256':digest(video),'identities_sha256':digest(identities),'plan_sha256':digest(plan),'decoder_source_sha256':digest(__file__)}
    if d.get('status')!='EXACT_FRAME_REPAIR_COLOR_PAIR_PASS' or d.get('color_mismatches')!=0 or d.get('pyav_version')!=av.__version__:
        raise ValueError('Full paired color decoder gate not passed')
    if any(d.get(k)!=v for k,v in expected.items()):raise ValueError('Decoder acceptance proof input/source hash mismatch')
    return d
