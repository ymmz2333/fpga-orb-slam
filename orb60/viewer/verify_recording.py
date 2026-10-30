"""Validate recorded *physical FPGA* output and read-only SLAM telemetry."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import numpy as np
from protocol import Snapshot
from sources import Recording


def records(path):
    pattern=r'FPGA_ORB_NET frame=(\d+) role=(\d+) count=(\d+)[^\n]*?record_crc=(\d+) cpu_orb=(\d+)'
    return [tuple(map(int,m)) for m in re.findall(pattern,path.read_text())]


def check_pose(poses):
    poses=np.asarray(poses,dtype=np.float64).reshape(-1,4,4)
    assert np.isfinite(poses).all()
    np.testing.assert_allclose(poses[:,3,:],np.tile([0,0,0,1],(len(poses),1)),atol=1e-5)
    rotations=poses[:,:3,:3]
    np.testing.assert_allclose(rotations@rotations.transpose(0,2,1),np.tile(np.eye(3),(len(poses),1,1)),atol=1e-4)
    np.testing.assert_allclose(np.linalg.det(rotations),1,atol=1e-4)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--live',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    state=json.loads((a.run/'status.json').read_text());assert state['state']=='COMPLETED' and state['exit_code']==0
    assert state['integration_pass'] and state['cpu_orb_calls']==0
    actual=records(a.run/'output.log');reference=records(a.reference/'output.log')
    assert len(actual)==len(reference)==state['frames']==2273
    assert actual==reference,'Physical FPGA frame order, count, record CRC or CPU fallback changed'
    assert all(row[-1]==0 for row in actual)
    with (a.run/'FeatureTimeStats.csv').open() as f:stats=list(csv.DictReader(f))
    assert len(stats)==len(actual)
    by_stamp={int(row['timestamp_ns']):row for row in stats}
    with (a.run/'source_frames.csv').open() as f:source={int(row['timestamp_ns']):row for row in csv.DictReader(f)}
    recording=Recording(a.run/'telemetry');tracked=0;max_points=0;max_keys=0;last=-1
    for path in recording.paths:
        snap=Snapshot.decode(path.read_bytes());meta=snap.meta;index=meta['frame_index']
        assert index>last;last=index
        assert int(stats[index]['timestamp_ns'])==meta['timestamp_ns']
        assert int(by_stamp[meta['timestamp_ns']]['count'])==meta['feature_count']
        assert meta['source']=='fpga' and meta['cpu_orb_calls']==0
        assert 0<=int(source[meta['timestamp_ns']]['source_frame_index'])<2297
        assert meta['pose_valid']==(meta['state']==2)
        if meta['pose_valid']:tracked+=1;check_pose(meta['pose_twc'])
        assert len(np.unique(snap.points['id']))==len(snap.points)
        assert len(np.unique(snap.keyframes['id']))==len(snap.keyframes)
        if len(snap.keyframes):check_pose(snap.keyframes['twc'])
        max_points=max(max_points,len(snap.points));max_keys=max(max_keys,len(snap.keyframes))
    assert tracked>0 and max_points>0 and max_keys>0
    live=json.loads(a.live.read_text());assert live['status']=='PASS' and live['frames_received']>=20
    result=dict(status='PASS',physical_fpga_frames=len(actual),display_snapshots=len(recording.paths),
                sampled_valid_poses=tracked,max_points=max_points,max_keyframes=max_keys,
                record_crc_count_order_equal_reference=True,cpu_orb_calls=0,
                source_timestamp_mapping_verified=True,finite_rigid_poses_verified=True,
                changing_live_snapshots=live['frames_received'],
                historical_run_fps=state['processing_fps'],
                performance_note='This retained telemetry run predates the user-reported 57 FPS DDR write-combining update; it does not measure that update.',
                reference_log_sha256=hashlib.sha256((a.reference/'output.log').read_bytes()).hexdigest(),
                run_log_sha256=hashlib.sha256((a.run/'output.log').read_bytes()).hexdigest())
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
