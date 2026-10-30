"""Pair immutable routed IP, native frame RTL and legal-mask unit evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def check(job,output):
    root=read(job/'status.json');assert root['State']=='SUCCEEDED' and root['Stage']=='COMPUTER_GATES_COMPLETE'
    route=Path(root['RouteJob']);frame=Path(root['FrameJob']);unit=Path(root['MergeAxisJob'])
    r=read(route/'status.json');f=read(frame/'status.json');u=read(unit/'status.json')
    assert r['State']==f['State']==u['State']=='SUCCEEDED'
    frequency=r['FrequencyMHz'];assert frequency in (100,125)
    assert r['LayerPpc']==4 and r['Part']=='xc7z015clg485-2'
    assert float(r['Timing']['wns_ns'])>=0 and float(r['Timing']['whs_ns'])>=0
    assert float(r['Timing']['tns_ns'])==float(r['Timing']['ths_ns'])==0
    assert f['Stage']=='COMPLETE' and u['Stage']=='COMPLETE'
    origins={'layer2':Path(r['LayerHlsJob']),'descriptor':Path(r['DescriptorHlsJob'])}
    for kernel,key in (('layer2','LayerHlsJob'),('descriptor','DescriptorHlsJob')):
        assert Path(f[key]).resolve()==origins[kernel].resolve()
        state=read(origins[kernel]/'status.json');assert state['State']=='SUCCEEDED' and state['Cosim'] and state['PeriodNs']==1000/frequency
        for entry in read(origins[kernel]/'source_manifest.json'):
            assert digest(origins[kernel]/'inputs'/entry['Path']).upper()==entry['SHA256']
    for entry in read(frame/'rtl_manifest.json'):
        assert digest(origins[entry['kernel']]/f"projects/{entry['kernel']}/solution1/syn/verilog/{entry['name']}")==entry['sha256']
    ip_root=Path(r['ScratchRoot'])
    for entry in read(route/'inputs/ip_manifest.json'):
        assert digest(ip_root/entry['Path']).upper()==entry['SHA256']
    protocol=read(Path(f['ProtocolJob'])/'status.json');assert protocol['State']=='SUCCEEDED' and protocol['Stage']=='COMPLETE'
    assert Path(protocol['LayerHlsJob']).resolve()==origins['layer2'].resolve()
    assert Path(protocol['DescriptorHlsJob']).resolve()==origins['descriptor'].resolve()
    unit_proof=read(unit/'result.json');assert unit_proof['status']=='PASS' and unit_proof['cases']==17 and unit_proof['reset']['reset_live']
    assert read(Path(u['HlsJob'])/'status.json')['PeriodNs']==1000/frequency,'Serializer must be regenerated at release clock'
    relative='inputs/FPGA_ORB_HLS/fastv2/next/src/front4_stream.hpp'
    source=[(p/relative).read_text().split('void serialize_front4_quads(',1)[1] for p in (origins['layer2'],Path(u['HlsJob']))]
    assert source[0]==source[1]
    performance=read(frame/'performance.json')
    assert performance['status']=='PASS' and performance['frequency_mhz']==frequency and performance['layer_ppc']==4 and performance['rtl_unchanged']
    assert len(performance['runs'])==4 and all([x['selected'] for x in run['frames']]==[280,942,0] for run in performance['runs'])
    maximum=max(x['milliseconds'] for run in performance['runs'] for x in run['frames'])
    assert maximum<=16.67,'Do not generate a retained60FPS candidate above its modeled frame limit'
    record=dict(scope=f'Paired complete{frequency}MHz4PPC computer gates only; PS/cache/DDR PHY/representative-video P99/board unverified',
                route=str(route),frame=str(frame),unit=str(unit),maximum_modeled_frame_ms=maximum,
                engineering14ms_pass=maximum<14,part=r['Part'],frequency_mhz=frequency,
                checkpoint_sha256=digest(ip_root/'vivado/next_system_routed.dcp'))
    output.write_text(json.dumps(record,indent=2)+'\n');print('JOINT_RELEASE_PAIR_PASS max_modeled_ms',maximum)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();check(a.job,a.output)
