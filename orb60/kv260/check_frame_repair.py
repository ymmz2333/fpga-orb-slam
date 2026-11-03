"""Compare every reconstructed BGR pixel to the original SLICE5 decoder."""
import argparse
import json
from pathlib import Path
import time
import av
import cv2
import numpy as np
from .frame_decoder import ExactFrameDecoder,prepare_plan
from .run_network_system import digest


def check(video,identities,plan,output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh full color report required')
    cv2.setNumThreads(1);decoder=ExactFrameDecoder(video,identities,plan)
    report=dict(status='RUNNING',scope='PS decoder paired component, no DPU or whole FPS acceptance',
                video_sha256=digest(video),identities_sha256=digest(identities),plan_sha256=digest(plan),
                decoder_source_sha256=decoder.report['decoder_source_sha256'],pyav_version=av.__version__,frames=0)
    try:
        with av.open(str(video)) as container:
            stream=container.streams.video[0];stream.codec_context.thread_type='SLICE';stream.codec_context.thread_count=5
            for i,frame in enumerate(container.decode(stream)):
                ok,bgr=decoder.read()
                stamp=1000000000+int(frame.pts*frame.time_base*1000000000)
                if not ok or stamp!=decoder.timestamp_ns or not np.array_equal(bgr,frame.to_ndarray(format='bgr24')):
                    raise ValueError('Paired original BGR differs at frame%d'%i)
                report['frames']=i+1
                if (i+1)%300==0:print('FRAME_REPAIR_COLOR_CHECK',i+1,flush=True)
        if decoder.read()[0]:raise ValueError('Extra reconstructed frame')
        report.update(status='EXACT_FRAME_REPAIR_COLOR_PAIR_PASS',color_mismatches=0,decoder=decoder.report)
    except BaseException as error:report.update(status='FAILED',error=repr(error),decoder=decoder.report);raise
    finally:decoder.close();output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','frames','color_mismatches')}),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('video','identities','plan','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--prepare-from-diagnostic',type=Path)
    a=p.parse_args()
    if a.prepare_from_diagnostic:prepare_plan(a.prepare_from_diagnostic,a.plan,av.__version__)
    check(a.video,a.identities,a.plan,a.output)
