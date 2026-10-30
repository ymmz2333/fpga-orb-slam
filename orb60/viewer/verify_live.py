"""Verify an actual display connection; no simulated packets are generated."""
import argparse
import csv
import json
from pathlib import Path
import socket
import time
from protocol import receive_snapshot


def main():
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--port',type=int,default=18765)
    p.add_argument('--seconds',type=float,default=12);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    with a.reference.open() as f:expected={int(r['timestamp_ns']):int(r['count']) for r in csv.DictReader(f)}
    frames=[];points=0;keys=0;state='UNKNOWN';end=time.monotonic()+a.seconds
    with socket.create_connection((a.host,a.port),5) as sock:
        sock.settimeout(3)
        while time.monotonic()<end:
            snap=receive_snapshot(sock);m=snap.meta
            if m.get('event')=='status':state=m['session_state'];continue
            assert m['source']=='fpga' and m['cpu_orb_calls']==0
            assert expected[m['timestamp_ns']]==m['feature_count']
            if frames:assert m['frame_index']>frames[-1]['frame_index']
            frames.append(dict(frame_index=m['frame_index'],timestamp_ns=m['timestamp_ns'],features=m['feature_count'],map_full=m['map_full']))
            points=max(points,len(snap.points));keys=max(keys,len(snap.keyframes))
    assert len(frames)>=20 and points>0 and keys>0,'Need at least20 changing snapshots to prove live updates'
    result=dict(status='PASS',scope='actual read-only RK telemetry over loopback SSH forwarding',
                frames_received=len(frames),max_points=points,max_keyframes=keys,source_state=state,
                feature_counts_equal_retained_fpga=True,frames=frames)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='frames'},indent=2))


if __name__=='__main__':main()
