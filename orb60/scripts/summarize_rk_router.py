"""Validate the RK router replay and compare its counters with the PC run."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


def load(path):return json.loads(path.read_text())
def rows(path):
    with path.open() as f:return list(csv.DictReader(f))
def distribution(values):
    ordered=sorted(values)
    return dict(min=min(values),mean=statistics.mean(values),p99=ordered[math.ceil(.99*len(ordered))-1],max=max(values))


def main():
    p=argparse.ArgumentParser();p.add_argument('--rk',type=Path,required=True)
    p.add_argument('--pc',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();rk=load(a.rk/'status.json');pc=load(a.pc/'status.json')
    assert rk['execution_platform']=='rk3588' and rk['architecture']=='aarch64'
    assert rk['exit_code']==0 and rk['integration_pass'] and rk['frames']==pc['frames']==2273
    assert rk['cpu_orb_calls']==0 and rk['hardware_requests']==2273
    assert rk['camera_sha256']==pc['camera_sha256']
    assert rk['source_sha256']==pc['source_sha256'],'PC/RK SLAM adapter source differs'
    features=rows(a.rk/'FeatureTimeStats.csv');pc_features=rows(a.pc/'FeatureTimeStats.csv')
    assert len(features)==len(pc_features)==2273
    for x,y in zip(features,pc_features):
        assert x['timestamp_ns']==y['timestamp_ns'] and x['count']==y['count'],'input/feature count mismatch'
        assert int(x['extractor_calls'])==0 and float(x['native_ms'])==0
    tracking=rows(a.rk/'TrackingStates.csv');assert len(tracking)==2273
    first=next(i for i,r in enumerate(tracking) if int(r['state_after'])==2)
    lost=sum(int(r['state_after'])!=2 for r in tracking[first:])
    poses=[[float(x) for x in line.split()] for line in (a.rk/'CameraTrajectory.txt').read_text().splitlines() if line.strip()]
    assert poses and all(len(r)==8 and all(math.isfinite(x) for x in r) for r in poses)
    assert all(abs(sum(x*x for x in r[4:])-1)<1e-3 for r in poses)
    assert all(x[0]<y[0] for x,y in zip(poses,poses[1:]))
    net=rk['network_delta']['eth0']
    image_payload_bytes=2273*(960*720+64)
    feature_payload_bytes=sum(int(x['count'])*64+128+1024+64 for x in features)
    assert rk['network_interface']=='eth0' and 'dev eth0' in rk['fpga_route']
    assert net['tx_bytes']>=image_payload_bytes and net['rx_bytes']>=feature_payload_bytes
    assert net['tx_errors']==net['rx_errors']==0
    assert all(net[k]>=0 for k in net)
    log=(a.rk/'output.log').read_text()
    engine=[int(v)/1e6 for v in re.findall(r'FPGA_ORB_NET .*?engine_ns=(\d+)',log)]
    assert len(engine)==2273
    total=[]
    with (a.rk/'TrackingTimeStats.txt').open() as f:
        next(f)
        for line in f:
            if line.strip():total.append(float(line.split(',')[-1]))
    assert len(total)==2273
    result=dict(status='PASS' if not lost else 'COMPLETED_WITH_TRACKING_LOSS',
        scope='RK3588 wired eth0 to FPGA via LAN router bridge; PC SSH orchestration only',
        frames=2273,cpu_orb_calls=0,first_tracking_index=first,tracked_frames=rk['tracking_states'].get('2',0),
        post_initialization_non_ok_frames=lost,trajectory_poses=len(poses),
        keyframe_poses=sum(bool(s.strip()) for s in (a.rk/'KeyFrameTrajectory.txt').read_text().splitlines()),
        all_frame_feature_counts_equal_pc=True,adapter_source_equal_pc=True,
        ethernet_counters=net,frame_payload_bytes=image_payload_bytes,feature_payload_bytes=feature_payload_bytes,
        network_delta=rk['network_delta'],fpga_route=rk['fpga_route'],
        fpga_engine_ms=distribution(engine),feature_request_ms=distribution([float(x['read_ms']) for x in features]),
        record_decode_ms=distribution([float(x['decode_ms']) for x in features]),tracking_total_ms=distribution(total),
        tracking_compute_fps=1000/statistics.mean(total),wall_seconds_including_startup=rk['wall_seconds'],
        pc_feature_request_ms=distribution([float(x['read_ms']) for x in pc_features]),pc_wall_seconds=pc['wall_seconds'],
        accuracy='Provisional borrowed calibration; no metric-scale/ATE claim')
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
