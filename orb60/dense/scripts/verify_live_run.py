"""Independent audit of actual FPGA requests, NPU placement and incremental point artifacts."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--gate',type=Path,required=True)
    p.add_argument('--source-frames',type=Path,required=True);a=p.parse_args()
    root=a.run;report=json.loads((root/'live_report.json').read_text())
    tracking=json.loads((root/'slam/status.json').read_text());worker=json.loads((root/'npu/worker.json').read_text())
    gate=json.loads(a.gate.read_text())
    assert report['state']=='COMPLETED' and tracking['state']=='COMPLETED' and tracking['exit_code']==0
    assert tracking['integration_pass'] and tracking['hardware_requests']==tracking['frames'] and tracking['cpu_orb_calls']==0
    assert gate['status']=='PASS' and hashlib.sha256(a.model.read_bytes()).hexdigest()==gate['model_sha256']
    assert len(worker['frames'])==report['npu_frames'] and all(f['hardware_run_us']>0 for f in worker['frames'])
    profile=(root/'npu/operator-profile.txt').read_text();nodes=[]
    for line in profile.splitlines():
        m=re.match(r'^\s*(\d+)\s+(\w+)\s+(\w+)\s+(NPU|CPU|GPU)\s+',line)
        if m:nodes.append(dict(op=m[2],target=m[4]))
    compute=[n for n in nodes if n['target']=='NPU' and n['op'] not in {'InputOperator','OutputOperator','Reshape','Transpose'}]
    assert len(compute)>=20 and not [n for n in nodes if n['target']!='NPU' and n['op'] not in {'InputOperator','OutputOperator','Resize'}]
    frames={int(r['timestamp_ns']):int(r['source_frame_index']) for r in csv.DictReader(a.source_frames.open())}
    dtype=np.dtype([('xyz','<f4',(3,)),('rgb','u1',(3,))]);total=0;ids=set()
    for chunk in report['chunks']:
        name='m%d_k%d'%(chunk['map_id'],chunk['keyframe_id']);key=(chunk['map_id'],chunk['keyframe_id'])
        assert key not in ids;ids.add(key)
        meta=json.loads((root/'chunks'/(name+'.json')).read_text())
        source=json.loads((root/'keyframes_live'/(name+'.json')).read_text())
        points=np.fromfile(root/'chunks'/(name+'.bin'),dtype=dtype)
        assert len(points)==meta['points']==chunk['points'] and 0<len(points)<=12000
        assert np.isfinite(points['xyz']).all() and np.isfinite(np.asarray(meta['twc'])).all()
        assert frames[source['timestamp_ns']]==meta['source_frame_index']==chunk['source_frame_index']
        assert source['keyframe_id']==meta['keyframe_id'] and len(source['observations'])>=20
        assert meta['fit']['inliers']>=20 and meta['fit']['slope']>0
        total+=len(points)
    assert len(ids)<=128 and total==report['points']<=2000000
    assert 0<report['first_chunk_seconds']<tracking['wall_seconds']-2
    buckets=2**int(np.ceil(np.log2(max(1,len(ids)))));display_bound=len(ids)*(200000//buckets)
    assert display_bound<=200000
    evidence=dict(status='PASS',actual_processing=True,frames=tracking['frames'],fpga_requests=tracking['hardware_requests'],
        cpu_orb_calls=0,npu_frames=len(worker['frames']),npu_compute_nodes=len(compute),
        chunks=len(ids),points=total,display_point_bound=display_bound,
        first_chunk_seconds=report['first_chunk_seconds'],native_wall_seconds=tracking['wall_seconds'],
        matched_model_sha256=gate['model_sha256'],same_accepted_numerical_gate=True,
        wrapper_note='Display service may intentionally linger after its native processing and NPU worker have completed')
    (root/'live_acceptance.json').write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence))


if __name__=='__main__':main()
