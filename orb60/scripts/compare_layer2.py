"""Evidence for each instance of every required pipeline; never collapse labels."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from compare_hls import extract


def measured_loops(job):
    loops=[]
    for report in (job/'projects/layer2/solution1/syn/report').glob('*_csynth.xml'):
        root=ET.parse(report).getroot()
        module=root.findtext('UserAssignments/TopModelName')
        summary=root.find('PerformanceEstimates/SummaryOfLoopLatency')
        if summary is None: continue
        for loop in summary:
            ii=loop.findtext('PipelineII')
            if ii is not None:
                loops.append(dict(module=module,label=loop.tag,II=int(ii),xml=str(report)))
    return loops


def main():
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True)
    p.add_argument('--front2',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    new=extract(a.job,'layer2','fastv2_layer2_hls')
    old=extract(a.front2,'front2','fastv2_front2_hls') if a.front2 else None
    loops=measured_loops(a.job)
    banked=(a.job/'inputs/FPGA_ORB_HLS/fastv2/next/src/banked_grid.hpp').exists()
    state=json.loads((a.job/'status.json').read_text(encoding='utf-8-sig'))
    ppc=state.get('LayerPpc',2);assert ppc in (2,4)
    counts={'UnpackPairs':1,'ForkLayerPairs':1,'RasterPairs':1,'MergePairs':1,
            'ReduceCandidateTokens':8 if banked else 1,'HorizontalGaussianPairs':1,'VerticalGaussianPairs':1,
            'ResizeSourcePairs':1,'DrainLastLevelPairs':1,'PackLayerPairs':2,
            'CollectLayerWords':2,'CountLayerCycles':1}
    if ppc==4:
        counts={name.replace('Pairs','Quads'):n for name,n in counts.items()}
        if state.get('LayerIoOverlap',False):
            del counts['CollectLayerWords'];counts.update(CollectLayerBlocks=2,EmitLayerReadWords=1)
    if banked:
        counts.update(RouteCandidateBanks=1,CollectBankWinners=1,EmitBankWinners=8)
    proof={}; passed=True
    for name,expected in counts.items():
        pattern=re.compile(r'(?:VITIS_LOOP_\d+_\d+_)*'+re.escape(name))
        matches=[loop for loop in loops if pattern.fullmatch(loop['label'])]
        proof[name]=dict(expected_instances=expected,actual=matches)
        passed &= len(matches)==expected and all(loop['II']==1 for loop in matches)
    result=dict(evidence_scope='HLS estimates and accepted co-simulation, no routed/board claim',
        standalone_front2=old,shared_layer2=new,transactions=21,loops=proof,
        pixel_parallelism=ppc,fast_staged=state.get('FastStaged',False),
        throughput_gate_pass=bool(passed),axi_all_64=all(v==64 for v in new['axi_data_widths'].values()) and len(new['axi_data_widths'])==4)
    rtl=(a.job/'projects/layer2/solution1/syn/verilog/fastv2_layer2_hls.v').read_text()
    addresses=re.findall(r'parameter\s+C_M_AXI_(\w+)_ADDR_WIDTH\s*=\s*(\d+)',rtl)
    result['axi_addr32']=len(addresses)==4 and all(int(v)==32 for _,v in addresses)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('ORB60_LAYER2_II '+str({name:[loop['II'] for loop in value['actual']] for name,value in proof.items()}))
    print(f'ORB60_LAYER2_COSIM_MAX front_only={old["cosim_latency_cycles"]["max"] if old else "reference_not_requested"} three_outputs={new["cosim_latency_cycles"]["max"]}')
    print('ORB60_LAYER2_HLS_RESOURCES '+str(new['resources_hls_estimate']))
    if not passed or not result['axi_all_64'] or not result['axi_addr32']:raise SystemExit('Layer pipeline/interface gate failed; retained comparison contains actual evidence')


if __name__=='__main__':main()
