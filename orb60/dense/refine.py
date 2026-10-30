"""Re-fuse measured NPU depth at a finer voxel size; immutable source, no network inference."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import resource
import cv2
import numpy as np
from .geometry import VoxelMap,backproject,consistent_points
from .ply import write_ply
from .replay import prepare_replay


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-frames',type=Path,required=True)
    p.add_argument('--voxel',type=float,default=.004);p.add_argument('--pixel-step',type=int,default=2)
    a=p.parse_args();a.source=a.source.resolve();a.output=a.output.resolve()
    if a.output.exists():raise ValueError('Choose a new refinement output; source results are immutable')
    if not .001<=a.voxel<=.02 or not 1<=a.pixel_step<=4:p.error('Invalid resolution')
    source_report=json.loads((a.source/'result.json').read_text())
    gate=json.loads((a.source/'artifact_acceptance.json').read_text())
    if gate['status']!='PASS':raise ValueError('Refinement requires an accepted real reconstruction')
    a.output.mkdir(parents=True)
    manifest=json.loads((a.source/'keyframes.json').read_text());reports=[];tick=time.monotonic();inputs={}
    for info in manifest['maps']:
        mid=info['map_id'];src=a.source/('map_%d'%mid);dst=a.output/src.name
        report=json.loads((src/'result.json').read_text());dst.mkdir()
        reference=report['reference_median_depth_raw'];usable=[]
        for frame in info['frames']:
            path=src/'keyframes'/(frame['name']+'.depth.npy')
            if not path.is_file():continue
            mask_path=path.with_name(frame['name']+'.depth-valid.png')
            depth=np.load(path);mask=cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE)>0
            if depth.shape!=(720,960) or mask.shape!=depth.shape:raise ValueError('Cached depth/mask shape mismatch')
            usable.append((frame,depth,mask,np.array(frame['k']),np.array(frame['twc'])))
            for artifact in [path,mask_path,a.source/frame['rgb']]:inputs[str(artifact.relative_to(a.source))]=sha(artifact)
        voxel=VoxelMap(reference*a.voxel,capacity=2000000);seen=0;accepted_total=0
        yy,xx=np.mgrid[0:720:a.pixel_step,0:960:a.pixel_step]
        for i,(frame,depth,mask,k,pose) in enumerate(usable):
            neighbors=[u for j,u in enumerate(usable) if i!=j and abs(j-i)<=4 and
                       np.linalg.norm(u[4][:3,3]-pose[:3,3])>reference*.01][:4]
            if not neighbors:continue
            valid=mask[yy,xx];uv=np.c_[xx[valid],yy[valid]]
            world=backproject(uv,depth[yy[valid],xx[valid]],k,pose)
            ok=consistent_points(world,[(u[1],u[2],u[3],u[4]) for u in neighbors])
            image=cv2.cvtColor(cv2.imread(str(a.source/frame['rgb'])),cv2.COLOR_BGR2RGB)
            voxel.add(world[ok],image[uv[ok,1],uv[ok,0]])
            seen+=len(world);accepted_total+=int(ok.sum())
            print('REFINED',mid,frame['keyframe_id'],'points',len(voxel.counts),flush=True)
        xyz,rgb=voxel.arrays();xyz/=reference;write_ply(dst/'dense.ply',xyz,rgb)
        for name in ['sparse.ply','poses.json','preview_features.json']:
            shutil.copy2(src/name,dst/name)
        replay=prepare_replay(a.source,dst,mid,a.source_frames)
        report.update(points=len(xyz),voxel_edge=voxel.edge/reference,
                      voxel_resolution_history=[r/reference for r in voxel.resolutions],
                      candidate_pixels=seen,accepted_pixels=accepted_total,pixel_step=a.pixel_step,
                      replay='replay.json',replay_summary=replay,baseline_points=report['points'],
                      baseline_voxel_edge=report['voxel_edge'],
                      refinement='Finer voxel fusion of the same NPU depth and multiview tests, no interpolated/duplicated points')
        (dst/'result.json').write_text(json.dumps(report,indent=2)+'\n');reports.append(report)
    elapsed=time.monotonic()-tick
    report=dict(source_report,maps=reports,refinement_seconds=elapsed,
                refinement_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                source_result_sha256=sha(a.source/'result.json'))
    (a.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    (a.output/'provenance.json').write_text(json.dumps(dict(source_result=str(a.source),cached_inputs_sha256=inputs,
        source_acceptance_sha256=sha(a.source/'artifact_acceptance.json'),
        code_sha256={n:sha(Path(__file__).parent/n) for n in ['refine.py','geometry.py','replay.py','ply.py']},
        seconds=elapsed,configuration=dict(voxel=a.voxel,pixel_step=a.pixel_step,capacity=2000000),
        no_tracking_rerun=True,no_network_inference_rerun=True),indent=2)+'\n')
    print(json.dumps(dict(status='COMPLETED',points=sum(r['points'] for r in reports),seconds=elapsed)))


if __name__=='__main__':main()
