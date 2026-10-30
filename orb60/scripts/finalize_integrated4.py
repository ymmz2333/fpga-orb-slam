"""Close joint gates only after current route/frame and immutable-source checks."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def run(job):
    state=read(job/'status.json');route=read(job/'route_status.json');original=read(job/'frame_status.json')
    assert route['State']==original['State']=='SUCCEEDED'
    frame=Path((job/'frame_metrics_job.txt').read_text(encoding='utf-8-sig').strip())
    fresh=read(frame/'status.json');assert fresh['State']=='SUCCEEDED' and fresh['Stage']=='COMPLETE'
    old=read(Path(original['FrameJob'])/'performance.json');new=read(frame/'performance.json')
    assert old['frequency_mhz']==new['frequency_mhz']==100 and len(old['runs'])==len(new['runs'])==4
    for prior,current in zip(old['runs'],new['runs']):
        for name in ('ddr_beats_per_cycle','seed','random_stall_percent','read_initial_delay_cycles'):assert prior[name]==current[name]
        assert current['axi_metric_version']==2
        for a,b in zip(prior['frames'],current['frames']):
            for name in ('cycles','read_bytes','write_bytes','selected','layers'):assert a[name]==b[name],f'Stat-only change affected{name}'
            for port in b['axi_ports']:
                assert port['read_outstanding_cycle_sum']<=port['read_pending_cycles']*port['read_outstanding_max']
    command=[sys.executable,str(Path(__file__).with_name('compare_native_architecture.py')),'--candidate',str(frame),
        '--baseline',state['BaselineFrameJob'],'--output',str(job/'metrics_comparison')]
    subprocess.run(command,check=True)
    audit=job/'comparison_audit';audit.mkdir(exist_ok=False)
    (audit/'stats_only.json').write_text(json.dumps(dict(status='PASS',old_frame=original['FrameJob'],new_frame=str(frame),
        frames=12,cycles_bytes_selection_all_identical=True,
        correction='V1 read_pending_cycles omitted cycles with RVALID. V2 includes every outstanding read; wait-for-data retained separately. Historical conditional means are invalid; raw evidence preserved.',
        raw_historical_evidence_unchanged=True),indent=2)+'\n')
    prior=read(Path(state['PreviousIntegratedJob'])/'status.json')
    assert read(Path(prior['MergeAxisJob'])/'status.json')['State']=='SUCCEEDED'
    state.update(State='SUCCEEDED',Stage='COMPUTER_GATES_COMPLETE',RouteJob=route['RouteJob'],FrameJob=str(frame),
        OriginalFrameJob=original['FrameJob'],MergeAxisJob=prior['MergeAxisJob'],
        Scope='Exact4PPC100MHz HLS/protocol/native/fullroute gates; corrected stat-only replay; PS/board/P99 unverified')
    (job/'status.json').write_text(json.dumps(state,indent=2)+'\n')
    print('INTEGRATED4_COMPLETE max_ms',max(x['milliseconds'] for r in new['runs'] for x in r['frames']))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);run(p.parse_args().job)
