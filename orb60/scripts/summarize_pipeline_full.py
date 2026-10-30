"""Validate the complete physical pipeline against retained input/feature evidence."""
import argparse
import csv
import json
import math
from pathlib import Path
import re


def load(p):return json.loads(p.read_text())
def rows(p):
    with p.open() as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser();p.add_argument('--full',type=Path,required=True)
    p.add_argument('--paired-pipeline',type=Path,required=True);p.add_argument('--pc-reference',type=Path,required=True)
    p.add_argument('--board-log',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();s=load(a.full/'status.json');paired=load(a.paired_pipeline/'status.json');pc=load(a.pc_reference/'status.json')
    assert s['state']=='COMPLETED' and s['exit_code']==0 and s['integration_pass'] and s['frames']==2273
    assert s['architecture']=='aarch64' and s['feature_mode']=='fpga-pipeline' and s['cpu_orb_calls']==0
    for key in ('source_sha256','executable_sha256','library_sha256','camera_sha256'):assert s[key]==paired[key],key
    # Algorithm-facing SLAM sources are unchanged from the retained PC run.
    for name in ('src/Tracking.cc','src/ORBmatcher.cc'):assert s['source_sha256'][name]==pc['source_sha256'][name]
    assert s['camera_sha256']==pc['camera_sha256']
    features=rows(a.full/'FeatureTimeStats.csv');reference=rows(a.pc_reference/'FeatureTimeStats.csv')
    assert len(features)==len(reference)==2273
    assert [(r['timestamp_ns'],r['count']) for r in features]==[(r['timestamp_ns'],r['count']) for r in reference]
    assert all(int(r['extractor_calls'])==0 and float(r['native_ms'])==0 for r in features)
    def fingerprints(directory):
        return re.findall(r'FPGA_ORB_NET frame=(\d+) .*?count=(\d+) .*?record_crc=(\d+)',(directory/'output.log').read_text())
    full=fingerprints(a.full);short=fingerprints(a.paired_pipeline)
    assert len(full)==2273 and [int(r[0]) for r in full]==list(range(1,2274)) and full[:len(short)]==short
    states=rows(a.full/'TrackingStates.csv');first=next(i for i,r in enumerate(states) if int(r['state_after'])==2)
    non_ok=sum(int(r['state_after'])!=2 for r in states[first:]);assert non_ok==0
    poses=[[float(x) for x in line.split()] for line in (a.full/'CameraTrajectory.txt').read_text().splitlines() if line.strip()]
    assert len(poses)==2163 and all(len(r)==8 and all(math.isfinite(x) for x in r) for r in poses)
    assert all(abs(sum(x*x for x in r[4:])-1)<1e-3 for r in poses)
    assert all(x[0]<y[0] for x,y in zip(poses,poses[1:]))
    net=s['network_delta']['eth0'];input_bytes=2273*(691200+64)
    output_bytes=sum(64+128+1024+64*int(r['count']) for r in features)
    assert s['network_interface']=='eth0' and 'dev eth0' in s['fpga_route']
    assert net['tx_bytes']>=input_bytes and net['rx_bytes']>=output_bytes
    assert net['tx_errors']==net['rx_errors']==0
    summaries=[json.loads(line.split(' ',1)[1]) for line in a.board_log.read_text().splitlines() if line.startswith('PIPELINE_SUMMARY ')]
    board=next(r for r in reversed(summaries) if r['received']==2273)
    assert board['processed']==board['sent']==2273 and board['fatal']==0
    assert board['ready_high']<=3 and board['result_high']<=3 and board['all_three_ns']>0
    result=dict(status='PASS',frames=2273,fps=s['processing_fps'],processing_seconds=s['processing_seconds'],
                ordered=True,no_dropped_frames=True,cpu_orb_calls=0,first_tracking_index=first,trajectory_poses=len(poses),
                post_initialization_non_ok=non_ok,all_frame_timestamp_and_count_equal_pc=True,
                first300_record_crc_equal_paired_run=True,source_and_binary_equal_300frame_test=True,
                network_ms=s['network_ms'],submit_to_slam_consume_ms=s['latency_ms'],slam_wait_ms=s['wait_ms'],
                host_queues=s['pipeline'],board_queues=board,ethernet=net,
                image_payload_bytes=input_bytes,result_payload_bytes=output_bytes,
                scope='Recorded2273-frame video; real RK eth0/router/150MHz FPGA; provisional calibration')
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
