"""Hash-pair accepted frequency RTL/IP, route, frame and4GB/s evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def paired_export(source,exported,kernel):
    if digest(source)==digest(exported):return 'byte_identical'
    # AMD export appends this exact simulation-only monitor to the top. The
    # monitor include is translate_off, and its standalone flag has no user.
    # Permit only that known block and trailing whitespace; any other HDL
    # difference fails. Keep both raw hashes in the acceptance record.
    top=f'fastv2_{kernel}_hls'
    assert source.name==exported.name==top+'.v','Unexpected exported HDL difference'
    block='\n\nreg find_df_deadlock = 0;\n// synthesis translate_off\n'+f'`include "{top}_hls_deadlock_detector.vh"\n'+'// synthesis translate_on\n'
    text=exported.read_text();assert text.count(block)==1,'Unexpected export instrumentation'
    assert text.replace(block,'',1).rstrip()==source.read_text().rstrip(),'Export changes synthesizable core code'
    return 'exact_AMD_simulation_monitor_only'


def main():
    p=argparse.ArgumentParser();p.add_argument('--pair',type=Path,required=True)
    p.add_argument('--joint',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();proof=read(a.joint)
    assert proof['status']=='PASS' and Path(proof['pair']).resolve()==a.pair.resolve()
    assert proof['nominal_frequency_mhz']==150
    pair=read(a.pair/'status.json');route=Path(proof['route']);frame=Path(proof['frame']);protocol=Path(proof['protocol'])
    state=read(route/'status.json');scratch=Path(state['ScratchRoot'])
    assert state['State']=='SUCCEEDED' and state['Stage']=='COMPLETE'
    assert state['Part']=='xc7z015clg485-2' and state['LayerPpc']==4
    for metric in ('tns_ns','ths_ns','tpws_ns','setup_failed_endpoints','hold_failed_endpoints','pulse_failed_endpoints'):
        assert float(state['Timing'][metric])==0,metric
    assert float(state['Timing']['wns_ns'])>=0 and float(state['Timing']['whs_ns'])>=0
    assert (scratch/'vivado/.vivado_timing_success').is_file()
    origins={kernel:Path(pair[key]) for kernel,key in (('layer2','LayerHlsJob'),('descriptor','DescriptorHlsJob'))}
    for root in (route,frame,protocol):
        item=read(root/'status.json');assert item['State']=='SUCCEEDED' and item['Stage']=='COMPLETE'
        for kernel,key in (('layer2','LayerHlsJob'),('descriptor','DescriptorHlsJob')):
            assert Path(item[key]).resolve()==origins[kernel].resolve()
    for kernel,root in origins.items():
        item=read(root/'status.json')
        assert item['State']=='SUCCEEDED' and item['Cosim'] and not item['NoExport']
        assert item['Part']=='xc7z015clg485-2' and abs(item['PeriodNs']-1000/150)<1e-9
        for record in read(root/'source_manifest.json'):
            assert digest(root/'inputs'/record['Path']).upper()==record['SHA256']
    for record in read(route/'tool_manifest.json'):
        assert digest(route/'inputs'/record['Path']).upper()==record['SHA256']
    ip_roots={kernel:root/f'projects/{kernel}/solution1/impl/ip' for kernel,root in origins.items()}
    for record in read(route/'inputs/ip_manifest.json'):
        relative=Path(record['Path'].replace('\\','/'))
        assert relative.parts[0]=='ip' and relative.parts[1] in ('layer','desc')
        kernel='layer2' if relative.parts[1]=='layer' else 'descriptor'
        source=ip_roots[kernel]/Path(*relative.parts[2:])
        assert digest(scratch/relative).upper()==digest(source).upper()==record['SHA256']
    export_checks=[]
    for record in read(frame/'rtl_manifest.json'):
        root=origins[record['kernel']]
        source=root/f"projects/{record['kernel']}/solution1/syn/verilog/{record['name']}"
        assert digest(source)==record['sha256']
        copies=list(ip_roots[record['kernel']].rglob(record['name']))
        assert len(copies)==1,'Ambiguous or missing exported RTL:'+record['name']
        kind=paired_export(source,copies[0],record['kernel'])
        if kind!='byte_identical':export_checks.append(dict(name=record['name'],kind=kind,
            simulated_sha256=record['sha256'],exported_sha256=digest(copies[0])))
    for record in read(protocol/'test_manifest.json'):
        assert digest(protocol/record['Path']).upper()==record['SHA256']
    board=Path((a.pair/'board_4gb_job.txt').read_text(encoding='utf-8-sig').strip())
    board_state=read(board/'status.json');board_perf=read(board/'performance.json')
    assert board_state['State']=='SUCCEEDED' and board_state['Stage']=='COMPLETE'
    assert Path(board_state['SourceFrameJob']).resolve()==frame.resolve()
    assert board_perf['status']=='PASS' and board_perf['legacy_replay_exact'] and board_perf['rtl_unchanged']
    assert len(board_perf['runs'])==4
    assert read(board/'rtl_manifest.json')==read(frame/'rtl_manifest.json')
    for run in board_perf['runs']:
        assert run['clock_period_ps']==proof['simulation_period_ps']
        assert run['ddr_capacity_bytes_per_second']==4000000000
        assert [item['selected'] for item in run['frames']]==[280,942,0]
    maximum=max(item['milliseconds'] for run in board_perf['runs'] for item in run['frames'])
    adequate=[run for run in board_perf['runs'] if run['random_stall_percent']==0 and
              run['read_initial_delay_ns']==[0,50]]
    assert len(adequate)==1,'Missing sufficient-bandwidth selection profile'
    primary=adequate[0]['frames']
    assert max(item['milliseconds'] for item in primary)<=16.67
    checkpoint=scratch/'vivado/next_system_routed.dcp'
    result=dict(status='PASS',part=state['Part'],frequency_mhz=150,ps_fclk_input_mhz=100,
        checkpoint=str(checkpoint.resolve()),checkpoint_sha256=digest(checkpoint),
        pair=str(a.pair.resolve()),route=str(route),frame=str(frame),protocol=str(protocol),board_4gb=str(board),
        maximum_4gb_frame_ms=maximum,
        performance_selection='4GB/s, no synthetic random stalls, initial read delay0..50ns; other profiles diagnostic only',
        sufficient_bandwidth_frames=[dict(points=item['selected'],milliseconds=item['milliseconds'],
            equivalent_fps=item['equivalent_fps']) for item in primary],
        sufficient_bandwidth_engineering14ms_pass=max(item['milliseconds'] for item in primary)<=14,
        export_monitor_differences=export_checks,
        scope='Computer-gated paired checkpoint only; no PS/board programming or physical-board FPS proof')
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(f'FREQUENCY_RELEASE_PAIR_PASS frequency=150MHz sufficient_ddr_max_ms={max(item["milliseconds"] for item in primary):.5f}')


if __name__=='__main__':main()
