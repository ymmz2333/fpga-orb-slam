"""Profile a verified decoder prefix alone; never report this as DPU/system FPS."""
import argparse
import cProfile
import json
from pathlib import Path
import platform
import pstats
import time
from ..paired_frame_decoder import ExactPairedDecoder,validate_proof
from ..direct_gray import digest


def run(video,identities,color_identities,proof,plan,decoder_proof,output,frames=600):
    if platform.machine()!='aarch64' or type(frames)!=int or not 1<=frames<=2297:raise ValueError('Native bounded decoder profile required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    gate=validate_proof(decoder_proof,video,identities,color_identities,proof,plan)
    decoder=ExactPairedDecoder(video,identities,color_identities,proof,plan);profile=cProfile.Profile()
    state=dict(status='RUNNING',scope='Isolated checked decoder prefix, no FIFO/PL/SLAM/DPU/GPU; profiler callback wall times include waiting and may overlap. No system FPS claim.',
               requested_prefix_frames=frames,full_source_frames=gate['frames'],decoder_proof_sha256=digest(decoder_proof),profiler_source_sha256=digest(__file__))
    cpu=time.process_time();wall=time.monotonic()
    try:
        profile.enable()
        for i in range(frames):
            item=decoder.read()
            if item is None or item[0]!=i:raise ValueError('Incomplete verified profile prefix')
        profile.disable()
        state.update(status='VERIFIED_PAIRED_DECODER_PREFIX_PROFILE_CAPTURED',checked_prefix_frames=frames,
                     wall_seconds=time.monotonic()-wall,process_cpu_seconds=time.process_time()-cpu,
                     decoder_prefix_report=decoder.report)
    except BaseException as e:state.update(status='FAILED',error=repr(e));raise
    finally:
        profile.disable();profile.dump_stats(str(output/'decode.profile'));decoder.close()
        stats=pstats.Stats(profile)
        state['top_self_callbacks']=[dict(file=k[0],line=k[1],function=k[2],calls=v[1],self_seconds=v[2],inclusive_seconds=v[3])
                                    for k,v in sorted(stats.stats.items(),key=lambda x:x[1][2],reverse=True)[:20]]
        (output/'PROFILE.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps({k:state[k] for k in ('status','checked_prefix_frames','wall_seconds','process_cpu_seconds','top_self_callbacks')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('video','identities','color_identities','proof','plan','decoder_proof','output'):p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    p.add_argument('--frames',type=int,default=600);run(**vars(p.parse_args()))
