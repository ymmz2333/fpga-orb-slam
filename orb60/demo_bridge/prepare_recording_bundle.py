"""Attach an existing, provably same-run dense result to a fixed sparse map."""
import argparse,csv,json,math,shutil
from pathlib import Path
from .dense_environment import write,validate
from .map_bundle import seal
from .export_map import prepare
from orb60.dense.ply import read_ply


def rows(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser();p.add_argument('sparse',type=Path);p.add_argument('dense',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Use a fresh output folder; preserve prior map')
    report=json.loads((a.dense/'map_0/result.json').read_text())
    if report['map_id']!=0:raise ValueError('Explicit map0 recording expected')
    for name in ['keyframes.csv','observations.csv']:
        sparse=rows(a.sparse/name);dense=rows(a.dense/'slam/keyframes/map_0'/name)
        common=set(sparse[0])&set(dense[0])
        if len(sparse)!=len(dense) or not all(all(x[k]==y[k] for k in common) for x,y in zip(sparse,dense)):
            raise ValueError('Dense result belongs to another SLAM world: '+name)
    # Historical exports include duplicate pyramid observations and a small
    # number of weak landmarks. Apply the established localization selection;
    # never relax the current >=3 distinct-keyframe map gate.
    staging=a.output.with_name(a.output.name+'_source')
    shutil.copytree(a.sparse,staging)
    (staging/'map_id.txt').write_text('0\n')
    selection=prepare(staging,a.output)
    shutil.copyfile(a.sparse/'camera_orb.csv',a.output/'camera_orb.csv')
    scale=float(report['world_scale'])
    if not math.isfinite(scale) or scale<=0:raise ValueError('Invalid display normalization')
    xyz,rgb=read_ply(a.dense/'map_0/dense.ply');xyz=xyz/scale
    target=a.output/'dense_environment.bin'
    write(target,xyz,rgb,a.output/'points.csv',a.output/'camera_orb.csv')
    count=validate(target,a.output/'points.csv',a.output/'camera_orb.csv')
    version=seal(a.output,a.output/'camera_orb.csv',0)
    evidence=dict(sparse_coordinates_unchanged=True,selection=selection,keyframes=len(rows(a.output/'keyframes.csv')),
                  observations=len(rows(a.output/'observations.csv')),dense_points=count,
                  undo_display_scale=scale,coordinates='original raw SLAM world; no trajectory fitting',version=version)
    (a.output/'dense_association.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence))


if __name__=='__main__':main()
