"""Joint frequency evidence: require exact pairing, hard route and native gates."""
import argparse
import json
from pathlib import Path
import re

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))

def utilization(path):
    text=path.read_text();result={}
    for name,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('slice','Slice'),('bram_tile','Block RAM Tile'),('dsp','DSPs')]:
        m=re.search(r'^\|\s*'+re.escape(label)+r'\s*\|\s*([\d.,]+)\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*([\d,]+)\s*\|\s*([\d.]+)',text,re.M)
        assert m,label
        result[name]=dict(used=(float if name=='bram_tile' else int)(m[1].replace(',','')),total=int(m[2].replace(',','')),percent=float(m[3]))
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--pair',type=Path,required=True)
    p.add_argument('--route',type=Path,required=True);p.add_argument('--frame',type=Path,required=True)
    p.add_argument('--protocol',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();pair=read(a.pair/'status.json');route=read(a.route/'status.json')
    frame=read(a.frame/'status.json');protocol=read(a.protocol/'status.json');perf=read(a.frame/'performance.json')
    assert pair['State']=='SUCCEEDED' and pair['Stage']=='C_RTL_PAIR_COMPLETE'
    assert all(item['State']=='SUCCEEDED' and item['Stage']=='COMPLETE' for item in (route,frame,protocol))
    for item in (route,frame,protocol):
        for key in ('LayerHlsJob','DescriptorHlsJob'):
            assert Path(item[key]).resolve()==Path(pair[key]).resolve(),key
    assert perf['status']=='PASS' and perf['rtl_unchanged'] and len(perf['runs'])==4
    period=round(pair['PeriodNs']*1000)
    assert perf['clock_period_ps']==period and abs(route['FrequencyMHz']-1000/pair['PeriodNs'])<1e-6
    timing=route['Timing'];assert float(timing['wns_ns'])>=0 and float(timing['whs_ns'])>=0
    for key in ('tns_ns','ths_ns','tpws_ns','setup_failed_endpoints','hold_failed_endpoints','pulse_failed_endpoints'):
        assert float(timing[key])==0,key
    # The strict route script already requires coverage, no severe DRC, no missing routes.
    assert route['ExtendedDiagnostics'] and not route['PostRoutePhysOptApplied']
    root=Path(route['ScratchRoot'])
    assert (root/'vivado/.vivado_timing_success').is_file()
    period_proof=(a.route/'reports/post_route_clocks.tsv').read_text()
    periods=[float(line.split('\t')[1]) for line in period_proof.splitlines()]
    assert any(abs(value-pair['PeriodNs'])<=0.0005 for value in periods)
    rows=[]
    for run in perf['runs']:
        assert run['clock_period_ps']==period and [f['selected'] for f in run['frames']]==[280,942,0]
        for f in run['frames']:
            rows.append(dict(points=f['selected'],milliseconds=f['milliseconds'],equivalent_fps=f['equivalent_fps'],
                ddr_bytes_per_second=run['ddr_capacity_bytes_per_second'],stall_percent=run['random_stall_percent'],
                initial_read_delay_ns=run['read_initial_delay_ns'],bytes=f['read_bytes']+f['write_bytes']))
    result=dict(status='PASS',scope='Fresh exact core RTL/protocol/shared-DDR simulation and complete routed top; physical board and PS pending',
        nominal_frequency_mhz=route['FrequencyMHz'],hls_period_ns=pair['PeriodNs'],simulation_period_ps=period,
        simulation_frequency_mhz=perf['frequency_mhz'],wns_ns=float(timing['wns_ns']),whs_ns=float(timing['whs_ns']),
        routed_resources=utilization(a.route/'reports/post_route_utilization.rpt'),frames=rows,
        maximum_modeled_frame_ms=max(row['milliseconds'] for row in rows),
        pair=str(a.pair.resolve()),route=str(a.route.resolve()),frame=str(a.frame.resolve()),protocol=str(a.protocol.resolve()),
        bitstream_generated=False,physical_board_verified=False,ps_modified=False)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('JOINT_FREQUENCY_COMPUTER_GATES_PASS frequency_mhz='+str(route['FrequencyMHz'])+' WNS='+timing['wns_ns'])

if __name__=='__main__':main()
