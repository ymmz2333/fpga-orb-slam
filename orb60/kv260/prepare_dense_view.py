"""Adapt real KV dense replay artifacts to the existing ORB Studio viewer schema."""
import argparse,csv,json,shutil
from pathlib import Path
import numpy as np
from .dense_fusion import save


def prepare(cloud,inputs,output,map_id=0):
    cloud=Path(cloud);inputs=Path(inputs);output=Path(output)
    if output.exists():raise ValueError('Fresh viewer result directory required')
    report=json.loads((cloud/f'map_{map_id}/result.json').read_text(encoding='utf-8'))
    if report['backend']!='quantized-reference' or report['status']!='HOST_REPLAY_PASS':raise ValueError('Expected completed selected QAT reference replay')
    output.mkdir(parents=True)
    for name in ('dense.ply','sparse.ply'):shutil.copy2(cloud/f'map_{map_id}'/name,output/name)
    reference=float(report['reference_median_depth_raw']);poses=json.loads((cloud/f'map_{map_id}/poses.json').read_text(encoding='utf-8'))
    for item in poses:
        pose=np.asarray(item['twc'],float);pose[:3,3]/=reference;item['twc']=pose.tolist()
    save(output/'poses.json',poses)
    manifest=json.loads((inputs/'keyframes.json').read_text(encoding='utf-8'))
    group=next(m for m in manifest['maps'] if m['map_id']==map_id);frame=next(f for f in group['frames'] if f['selected'])
    shutil.copy2(inputs/frame['rgb'],output/'preview_rgb.png')
    with (inputs/group['observations']).open(newline='',encoding='utf-8') as f:obs=[r for r in csv.DictReader(f) if int(r['keyframe_id'])==frame['keyframe_id']]
    save(output/'preview_features.json',[[float(r['u']),float(r['v'])] for r in obs])
    result={**report,'cloud':'dense.ply','sparse':'sparse.ply','poses':'poses.json','world_scale':1/reference,
            'preview_rgb':'preview_rgb.png','preview_features':'preview_features.json','preview_keyframe':frame['keyframe_id'],
            'preview_source_frame':frame['source_frame_index'],'coordinate_system':'normalized relative SLAM world; poses and cloud use the same recorded unit conversion',
            'hardware_verified':False,'source':'selected MiDaS QAT quantized-reference, recorded keyframes'}
    save(output/'result.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cloud',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(prepare(a.cloud,a.inputs,a.output)['points'])
