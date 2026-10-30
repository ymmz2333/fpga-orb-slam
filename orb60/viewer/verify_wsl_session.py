"""Acceptance for one physical WSL/FPGA session, including actual desktop metrics."""
import argparse
import csv
import json
from pathlib import Path
from verify_recording import records


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True);a=p.parse_args()
    state=json.loads((a.run/'status.json').read_text());session=json.loads((a.run/'session.json').read_text())
    assert session['state']==state['state']=='COMPLETED' and session['exit_code']==state['exit_code']==0
    assert state['integration_pass'] and state['cpu_orb_calls']==0
    actual=records(a.run/'output.log');reference=records(a.reference/'output.log')
    n=state['frames'];assert len(actual)==n and actual==reference[:n]
    with (a.run/'FeatureTimeStats.csv').open() as f:rows=list(csv.DictReader(f))
    with (a.reference/'FeatureTimeStats.csv').open() as f:expected=list(csv.DictReader(f))[:n]
    assert [(r['timestamp_ns'],r['count']) for r in rows]==[(r['timestamp_ns'],r['count']) for r in expected]
    metrics=json.loads((a.run/'desktop_metrics.json').read_text())
    assert metrics['source']=='live' and not metrics['previous_connections']
    assert metrics['display_fps']>=25 and metrics['received']>=n*.9
    assert metrics['displayed']>=metrics['received']*.9 and metrics['last_frame']==n-1
    result=dict(status='PASS',physical_fpga_frames=n,record_crc_count_order_equal=True,
                timestamps_and_counts_equal=True,cpu_orb_calls=0,compute_endpoint='PC WSL',
                input='recorded video streamed at original timestamps',processing_fps_paced=state['processing_fps'],
                desktop=metrics,limitation='Occasional approximately100ms display gaps remain; not a locked30FPS claim.')
    (a.run/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
