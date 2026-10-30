"""Bounded banking comparison: exact co-sim/II and actual generated memories."""
import argparse
import json
from pathlib import Path
import re


def compare(new,old,output):
    candidate=json.loads(new.read_text());baseline=json.loads(old.read_text())
    assert candidate['throughput_gate_pass'] and candidate['axi_all_64']
    report=candidate['shared_layer2'];prior=baseline['shared_layer2']
    root=Path(report['job'])
    rtl=(root/'projects/layer2/solution1/syn/verilog/fastv2_layer2_hls_p_anonymous_namespace_consume_and_select.v').read_text()
    banks=re.findall(r'^(tree(?:_\d+)?_U)\s*\(',rtl,re.M)
    loops=[v for k,v in report['pipelined_loops'].items() if k.endswith('BuildTournament')]
    result=dict(scope='HLS estimates/generated bank count/exact co-sim only; protocol/frame/route pending',
                candidate_hls_job=str(root),baseline_hls_job=prior['job'],banks=banks,
                build_loops=loops,resources_hls_estimate=report['resources_hls_estimate'],
                baseline_resources_hls_estimate=prior['resources_hls_estimate'],
                resource_delta={k:report['resources_hls_estimate'][k]-prior['resources_hls_estimate'][k]
                    for k in report['resources_hls_estimate']},
                cosim_latency_cycles=report['cosim_latency_cycles'],
                baseline_cosim_latency_cycles=prior['cosim_latency_cycles'])
    result['banking_gate_pass']=len(banks)==2 and len(set(banks))==2 and len(loops)==1 and loops[0]['II']<=2
    output.write_text(json.dumps(result,indent=2)+'\n')
    assert result['banking_gate_pass'], 'Actual memory banking/II differs; evidence retained'
    print('TOURNAMENT_BANKS_HLS_PASS banks=2 build_II='+str(loops[0]['II']))
    print('HLS_RESOURCE_DELTA '+str(result['resource_delta']))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('new','old','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();compare(a.new,a.old,a.output)
