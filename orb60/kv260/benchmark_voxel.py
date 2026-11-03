"""Compare exact PS voxel algorithms on saved real local RGB point blocks."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time
import numpy as np
from .voxel import PackedVoxelMap,ReferenceVoxelMap
from .dense_fusion import POINT,save


def run(source,output):
    source=Path(source);output=Path(output)
    if output.exists():raise ValueError('Fresh benchmark report required')
    maps={};hashes={}
    for meta_path in sorted((source/'dense/blocks').glob('*.json')):
        if meta_path.name.endswith(('.final.json','.anchors.json')):continue
        meta=json.loads(meta_path.read_text())
        if meta.get('event')!='chunk':continue
        path=meta_path.with_suffix('.bin');payload=path.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=meta['payload_sha256']:raise ValueError('Corrupted real local point block')
        points=np.frombuffer(payload,POINT);pose=np.asarray(meta['twc'])
        world=points['xyz']@pose[:3,:3].T+pose[:3,3]
        maps.setdefault(meta['map_id'],[]).append((world,points['rgb'].copy(),meta['voxel_edge']))
        hashes[str(path)]=hashlib.sha256(payload).hexdigest()
    mid=max(maps,key=lambda k:sum(len(x[0]) for x in maps[k]));items=maps[mid]
    xyz=np.concatenate([x[0] for x in items]);rgb=np.concatenate([x[1] for x in items]);edge=min(x[2] for x in items)
    if len(xyz)<1000:raise ValueError('Insufficient real points for benchmark')
    values={};products={}
    for name,cls in [('reference',ReferenceVoxelMap),('packed',PackedVoxelMap)]:
        times=[]
        for _ in range(5):
            voxel=cls(edge,2000000);began=time.monotonic_ns();voxel.add(xyz,rgb);times.append((time.monotonic_ns()-began)*1e-9)
        values[name]=times;products[name]=voxel
    a,b=products['reference'],products['packed']
    if a.edge!=b.edge or a.sums.tobytes()!=b.sums.tobytes() or a.counts.tobytes()!=b.counts.tobytes():
        raise ValueError('Voxel centroids/colors/counts differ from original algorithm')
    if any(x.tobytes()!=y.tobytes() for x,y in zip(a.arrays(),b.arrays())):raise ValueError('Final point/color bytes differ')
    report=dict(status='EXACT_VOXEL_BENCHMARK_PASS',scope='PS geometry microbenchmark, not whole-system FPS',
                machine=platform.machine(),map_id=mid,input_points=len(xyz),output_points=len(a.counts),
                seconds=values,speedup=float(np.median(values['reference'])/np.median(values['packed'])),
                input_sha256=hashes,centroids_colors_counts_byte_identical=True)
    save(output,report);print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(**vars(p.parse_args()))
