"""Independent artifact/frame/geometry checks on a real reconstruction."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dense.geometry import valid_pose
from dense.ply import read_ply
from dense.video import digest


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--result',required=True,type=Path)
    p.add_argument('--video',required=True,type=Path)
    p.add_argument('--frames-csv',required=True,type=Path)
    p.add_argument('--npu-gate',required=True,type=Path)
    p.add_argument('--prior-log',type=Path)
    a=p.parse_args();root=a.result
    report=json.loads((root/'result.json').read_text())
    gate=json.loads(a.npu_gate.read_text());assert gate['status']=='PASS'
    assert report['npu_model_sha256']==gate['model_sha256']
    assert report['video_sha256']==digest(a.video)
    tracking=json.loads((root/'slam/status.json').read_text())
    assert tracking['integration_pass'] and tracking['exit_code']==0 and tracking['cpu_orb_calls']==0
    stamps=[int(s) for s in (root/'slam/timestamps.txt').read_text().splitlines() if s]
    assert all(x<y for x,y in zip(stamps,stamps[1:]))
    requests=re.findall(r'FPGA_ORB_NET frame=(\d+).*?count=(\d+).*?record_crc=(\d+)',(root/'slam/output.log').read_text())
    assert len(requests)==len(stamps)==tracking['frames']
    assert [int(r[0]) for r in requests]==list(range(1,len(stamps)+1))
    crc_equal=None
    if a.prior_log:
        prior=re.findall(r'FPGA_ORB_NET frame=(\d+).*?count=(\d+).*?record_crc=(\d+)',a.prior_log.read_text())
        crc_equal=requests==prior[:len(requests)];assert crc_equal,'FPGA records changed'
    frames={int(r['timestamp_ns']):r for r in csv.DictReader(a.frames_csv.open())}
    index=json.loads((root/'keyframes.json').read_text())
    originals=[];point_count=0;max_reprojection=0
    for m in index['maps']:
        mid=m['map_id'];byid={f['keyframe_id']:f for f in m['frames']}
        buckets={}
        for frame in m['frames']:
            assert valid_pose(np.asarray(frame['twc']))
            assert frame['source_frame_index']==int(frames[frame['timestamp_ns']]['source_frame_index'])
            assert digest(root/frame['raw_rgb'])==frame['raw_rgb_sha256']
            if frame['selected']:
                bucket=int(np.floor(frame['source_pts_s']));buckets[bucket]=buckets.get(bucket,0)+1
            originals.append(frame)
        assert max(buckets.values(),default=0)<=2
        obs=root/'slam/keyframes'/('map_%d'%mid)/'observations.csv'
        for row in csv.DictReader(obs.open()):
            frame=byid[int(row['keyframe_id'])];pose=np.asarray(frame['twc']);k=np.asarray(frame['k'])
            point=np.array([float(row[c]) for c in ['x','y','z']])
            camera=pose[:3,:3].T@(point-pose[:3,3]);pixel=k@camera
            assert camera[2]>0 and int(row['observations'])>=3
            error=float(np.linalg.norm(pixel[:2]/pixel[2]-[float(row['u']),float(row['v'])]))
            max_reprojection=max(max_reprojection,error);assert error<=3.001
        map_report=json.loads((root/('map_%d'%mid)/'result.json').read_text())
        xyz,rgb=read_ply(root/('map_%d'%mid)/map_report['cloud'])
        assert len(xyz)==map_report['points'] and len(rgb)==len(xyz)
        assert len(xyz)>=50000 and np.isfinite(xyz).all()
        point_count+=len(xyz)
    chosen=[originals[i] for i in np.linspace(0,len(originals)-1,min(3,len(originals)),dtype=int)]
    wanted={f['source_frame_index']:f for f in chosen}
    cap=cv2.VideoCapture(str(a.video));color_checks=[]
    for i in range(max(wanted)+1):
        ok,image=cap.read();assert ok
        if i in wanted:
            saved=cv2.imread(str(root/wanted[i]['raw_rgb']))
            assert image.shape==saved.shape
            delta=np.abs(image.astype(np.int16)-saved.astype(np.int16))
            # Different FFmpeg builds may round YUV conversion by a code value.
            assert np.percentile(delta,99.9)<=2 and float(delta.mean())<=.25
            color_checks.append(dict(source_frame=i,mean_abs_code_error=float(delta.mean()),max_abs_code_error=int(delta.max())))
    cap.release()
    evidence=dict(status='PASS',frames=len(stamps),cpu_orb_calls=0,exact_source_frame_mapping=True,
                  separate_map_coordinates=True,keyframe_rate_at_most_two_per_second=True,
                  points=point_count,maximum_sparse_reprojection_px=max_reprojection,
                  raw_color_checks=color_checks,all_records_crc_equal_prior=crc_equal,
                  npu_gate_sha256=digest(a.npu_gate),scope='Artifact/frame/numerical acceptance; visual quality is reviewed separately')
    (root/'artifact_acceptance.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
