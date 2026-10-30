"""Append fresh125MHz comparison/bit evidence to the preserved100MHz package."""
import argparse
import json
from pathlib import Path
import re
from prepare_integrated4_publication import read,sha,copy,tree,selected,write

def run(a):
    job=a.job.resolve();repo=a.repo.resolve();root=read(job/'status.json');bit=read(job/'bit/status.json')
    assert root['State']==bit['State']=='SUCCEEDED' and root['Stage']=='COMPUTER_GATES_COMPLETE'
    pair=read(job/'bit/joint_validation.json');assert pair['frequency_mhz']==125 and pair['engineering14ms_pass']
    for ppc in (2,4):
        route=Path(root['Comparisons'][str(ppc)]['route']);frame=Path(root['Comparisons'][str(ppc)]['frame'])
        evidence=repo/('orb60/evidence/integrated4_125mhz' if ppc==4 else 'orb60/evidence/2ppc_125mhz')
        tree(route/'reports',evidence/'route');selected(route,evidence/'route',['status.json','tool_manifest.json'])
        selected(route/'inputs',evidence/'route/inputs',['ip_manifest.json','timing_checks.tcl','build_orb_system.tcl'])
        selected(frame,evidence/'native',['status.json','performance.json','rtl_manifest.json','test_manifest.json','profile_manifest.json','delay_audit.json'])
        tree(frame/'inputs',evidence/'native/inputs')
        for path in frame.glob('beats*.json'):copy(path,evidence/'native'/path.name)
        tree(job/f'frame{ppc}_comparison',evidence/'comparison')
        protocol=Path(read(frame/'status.json')['ProtocolJob']);selected(protocol,evidence/'protocol',['status.json','test_manifest.json'])
        tree(protocol/'inputs',evidence/'protocol/inputs')
        for kernel in ('layer2','descriptor'):
            selected(protocol/kernel,evidence/'protocol'/kernel,['status.json','result.json','config.json','rtl_manifest.json','reuse.json'])
            origin=Path(read(route/'status.json')['LayerHlsJob' if kernel=='layer2' else 'DescriptorHlsJob'])
            selected(origin,evidence/'hls'/kernel,['status.json','source_manifest.json'])
            accepted=job/('accepted_layer'+str(ppc) if kernel=='layer2' else 'accepted_descriptor')
            copy(accepted/'comparison.json',evidence/'hls'/kernel/'comparison.json')
            tree(origin/f'projects/{kernel}/solution1/syn/report',evidence/'hls'/kernel/'reports')
            selected(origin/f'projects/{kernel}/solution1/sim/report',evidence/'hls'/kernel/'reports',[f'fastv2_{kernel}_hls_cosim.rpt'])
            # Shared backend snapshot is kept once; both artifacts name its origin.
            frozen=repo/('orb60/frozen/integrated4_125mhz' if ppc==4 or kernel=='descriptor' else 'orb60/frozen/2ppc_125mhz')/kernel
            for entry in read(origin/'source_manifest.json'):
                assert sha(origin/'inputs'/entry['Path']).upper()==entry['SHA256']
                copy(origin/'inputs'/entry['Path'],frozen/'inputs'/entry['Path'])
            selected(origin,frozen,['status.json','source_manifest.json','hls.tcl'])
            driver=origin/f'projects/{kernel}/solution1/impl/ip/drivers/fastv2_{kernel}_hls_v1_0/src'
            for header in driver.glob('*_hw.h'):
                copy(header,evidence/'registers'/header.name)
                old=repo/'orb60/evidence/integrated4_100mhz/registers'/header.name
                def fields(path):return re.findall(r'#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\b',path.read_text())
                assert fields(old)==fields(header),'Register definitions differ across retained clocks'
    artifact=repo/'orb60/artifacts/integrated4_125mhz'
    selected(job/'bit',artifact,['orb60_125mhz.bit','status.json','joint_validation.json','bit_metrics.tsv','bit_check_timing.rpt','bit_route_status.rpt','bit_drc.rpt'])
    assert sha(artifact/'orb60_125mhz.bit')==bit['BitSha256'].lower()
    write(artifact/'artifact_manifest.json',dict(status='PASS',part='xc7z015clg485-2',frequency_mhz=125,layer_ppc=4,
        bit_sha256=bit['BitSha256'].lower(),checkpoint_sha256=pair['checkpoint_sha256'],joint_validation=pair,
        layer_hls_job=root['LayerHlsJob'],descriptor_hls_job=root['DescriptorHlsJob'],
        build_flags=dict(layer=dict(LayerPpc=4,FastStaged=True,LayerIoOverlap=True,LayerBramFifos=True),
            descriptor=dict(DescriptorWidthMode=2,DescriptorPrefetch=8,DescriptorPatch32=True)),
        ps_modified=False,physical_board_verified=False))
    unit=Path(root['MergeAxisJob']);dest=repo/'orb60/evidence/integrated4_125mhz/merge4'
    selected(unit,dest,['status.json','result.json','test_manifest.json','rtl_manifest.json'])
    tree(unit/'inputs',dest/'inputs')
    copy(job/'status.json',repo/'orb60/evidence/frequency_comparison/status.json')
    tree(job/'route2_startup_failure',repo/'orb60/evidence/frequency_comparison/route2_startup_failure')
    print('FREQUENCY_PUBLICATION_PREPARED bit',bit['BitSha256'].lower())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--job',type=Path,required=True);run(p.parse_args())
