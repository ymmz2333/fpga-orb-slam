"""Audit refinement against immutable measured source and same-run trajectory."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dense.ply import read_ply


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path)
    p.add_argument('--result',required=True,type=Path);a=p.parse_args()
    provenance=json.loads((a.result/'provenance.json').read_text())
    report=json.loads((a.result/'result.json').read_text())
    original=json.loads((a.source/'result.json').read_text())
    assert report['source_result_sha256']==sha(a.source/'result.json')
    assert report['npu_model_sha256']==original['npu_model_sha256']
    assert report['video_sha256']==original['video_sha256']
    assert provenance['source_acceptance_sha256']==sha(a.source/'artifact_acceptance.json')
    checked=0
    for name,digest in provenance['cached_inputs_sha256'].items():
        assert sha(a.source/name)==digest,name
        checked+=1
    manifest=json.loads((a.source/'reconstruction_keyframes.json').read_text())
    maps=[]
    for m in report['maps']:
        folder=a.result/('map_%d'%m['map_id']);old=a.source/folder.name
        xyz,rgb=read_ply(folder/'dense.ply');baseline,_=read_ply(old/'dense.ply')
        assert len(xyz)==m['points'] and len(baseline)<len(xyz)<=2000000
        assert np.isfinite(xyz).all() and len(np.unique(xyz,axis=0))==len(xyz)
        assert np.any(rgb[:,0]!=rgb[:,1]) and np.any(rgb[:,1]!=rgb[:,2])
        for reducer in (np.min,np.max):
            assert np.max(np.abs(reducer(xyz,axis=0)-reducer(baseline,axis=0)))<=.02
        for name in ['sparse.ply','poses.json']:assert sha(folder/name)==sha(old/name)
        info=next(i for i in manifest['maps'] if i['map_id']==m['map_id'])
        assert m['accepted_pixels']==sum(f.get('consistent_pixels',0) for f in info['frames'])
        replay=json.loads((folder/'replay.json').read_text())
        by_key={f['keyframe_id']:f for f in replay['frames'] if 'keyframe_id' in f}
        for f in info['frames']:
            saved=by_key[f['keyframe_id']];pose=np.array(f['twc']);pose[:3,3]*=m['world_scale']
            np.testing.assert_allclose(saved['twc'],pose,atol=1e-12)
            assert saved['source_frame_index']==f['source_frame_index']
            assert sha(folder/saved['rgb'])==sha(a.source/f['rgb'])
        maps.append(dict(map_id=m['map_id'],baseline_points=len(baseline),points=len(xyz),
                         accepted_source_pixels=m['accepted_pixels'],keyframes=len(by_key),replay_frames=len(replay['frames'])))
    evidence=dict(status='PASS',cached_inputs_verified=checked,maps=maps,same_model_video_poses_and_multiview_support=True,
                  no_tracking_or_network_inference_rerun=True)
    (a.result/'refinement_acceptance.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))


if __name__=='__main__':main()
