"""Same RK executable, same frames: synchronous versus bounded async transport."""
import argparse
import csv
import json
import math
from pathlib import Path
import re


def load(p):return json.loads(p.read_text())
def csvrows(p):
    with p.open() as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser();p.add_argument('--sync',type=Path,required=True)
    p.add_argument('--pipeline',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();sync=load(a.sync/'status.json');pipe=load(a.pipeline/'status.json')
    assert sync['feature_mode']=='fpga' and pipe['feature_mode']=='fpga-pipeline'
    for state in (sync,pipe):
        assert state['exit_code']==0 and state['integration_pass'] and state['cpu_orb_calls']==0
        assert state['unpaced'] and state['execution_platform']=='rk3588' and state['network_interface']=='eth0'
        assert 'dev eth0' in state['fpga_route']
        assert state['network_delta']['eth0']['tx_errors']==state['network_delta']['eth0']['rx_errors']==0
    for key in ('frames','source_sha256','camera_sha256','executable_sha256','library_sha256'):
        assert sync[key]==pipe[key],key
    rows=[csvrows(d/'FeatureTimeStats.csv') for d in (a.sync,a.pipeline)]
    assert len(rows[0])==len(rows[1])==sync['frames']
    assert [(r['timestamp_ns'],r['count']) for r in rows[0]]==[(r['timestamp_ns'],r['count']) for r in rows[1]]
    fingerprints=[]
    for d in (a.sync,a.pipeline):
        log=(d/'output.log').read_text()
        records=re.findall(r'FPGA_ORB_NET frame=(\d+) .*?count=(\d+) .*?record_crc=(\d+)',log)
        assert len(records)==sync['frames'] and [int(r[0]) for r in records]==list(range(1,sync['frames']+1))
        fingerprints.append(records)
    assert fingerprints[0]==fingerprints[1],'raw PL record CRC/count changed'
    tracking={}
    for name,d in (('sync',a.sync),('pipeline',a.pipeline)):
        states=csvrows(d/'TrackingStates.csv');first=next(i for i,r in enumerate(states) if int(r['state_after'])==2)
        non_ok=sum(int(r['state_after'])!=2 for r in states[first:])
        poses=[[float(v) for v in line.split()] for line in (d/'CameraTrajectory.txt').read_text().splitlines() if line.strip()]
        assert poses and all(len(r)==8 and all(math.isfinite(v) for v in r) for r in poses)
        assert all(abs(sum(v*v for v in r[4:])-1)<1e-3 for r in poses)
        tracking[name]=dict(first_ok=first,post_initialization_non_ok=non_ok,trajectory_poses=len(poses))
    result=dict(status='PASS',frames=sync['frames'],raw_record_crc_and_count_equal=True,ordered=True,cpu_orb_calls=0,
                same_executable_and_sources=True,tracking=tracking,
                sync_fps=sync['processing_fps'],pipeline_fps=pipe['processing_fps'],
                throughput_gain=pipe['processing_fps']/sync['processing_fps'],
                sync_network_ms=sync.get('network_ms'),pipeline_network_ms=pipe.get('network_ms'),
                pipeline_consume_latency_ms=pipe.get('latency_ms'),pipeline_wait_ms=pipe.get('wait_ms'),
                pipeline=pipe['pipeline'],accuracy='Borrowed calibration; parallel SLAM poses are not required byte-identical')
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
