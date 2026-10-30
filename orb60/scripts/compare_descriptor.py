"""Retain actual pipeline/AXI evidence for the exact descriptor candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from compare_hls import extract


def main():
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=extract(a.job,'descriptor','fastv2_descriptor_hls')
    vectors=json.loads((a.job/'descriptor_vectors/vectors.json').read_text())
    for name,digest in vectors['sha256'].items():
        if hashlib.sha256((a.job/'descriptor_vectors'/name).read_bytes()).hexdigest()!=digest:
            raise SystemExit('Frozen descriptor vector changed: '+name)
    loops=[]
    for report in (a.job/'projects/descriptor/solution1/syn/report').glob('*_csynth.xml'):
        root=ET.parse(report).getroot();summary=root.find('PerformanceEstimates/SummaryOfLoopLatency')
        if summary is None:continue
        for loop in summary:
            ii=loop.findtext('PipelineII')
            if ii is not None:loops.append(dict(module=root.findtext('UserAssignments/TopModelName'),label=loop.tag,II=int(ii)))
    state=json.loads((a.job/'status.json').read_text(encoding='utf-8-sig'))
    fusion=int(state.get('DescriptorMomentFusion',0))
    required=(('IssueRawPatchRows','ReceiveRawMomentWords','ReceiveBlurRowWords','BriefBits','CountDescriptorCycles')
              if fusion else ('MomentCenterRow','MomentSymmetricPairs','BriefBits','CountDescriptorCycles'))
    evidence={}
    for name in required:
        pattern=re.compile(r'(?:VITIS_LOOP_\d+_\d+_)*'+name)
        evidence[name]=[row for row in loops if pattern.fullmatch(row['label'])]
    pipeline_pass=all(len(rows)==1 and rows[0]['II']==1 for rows in evidence.values())
    interface_pass=len(result['axi_data_widths'])==4 and all(width==64 for width in result['axi_data_widths'].values())
    record=dict(scope='Exact independent golden/Csim/RTL and HLS estimates; no routed/board result',
                descriptor=result,transactions=len(vectors['cases']),a32_bins=vectors['bins'],
                frame_counts=vectors['frame_counts'],moment_fusion=fusion,required_loops=evidence,all_loops=loops,
                pipeline_gate_pass=pipeline_pass,axi_all_64=interface_pass)
    a.output.write_text(json.dumps(record,indent=2)+'\n')
    print('ORB60_DESCRIPTOR_HLS_RESOURCES '+str(result['resources_hls_estimate']))
    print('ORB60_DESCRIPTOR_II '+str({k:[r['II'] for r in v] for k,v in evidence.items()}))
    print('ORB60_DESCRIPTOR_COSIM_LATENCY '+str(result['cosim_latency_cycles']))
    if not pipeline_pass or not interface_pass:raise SystemExit('Descriptor pipeline/interface gate failed; actual evidence retained')


if __name__=='__main__':main()
