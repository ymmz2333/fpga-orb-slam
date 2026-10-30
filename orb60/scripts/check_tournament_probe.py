"""Check actual II and chunk widths in a bounded tournament synthesis probe."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from compare_layer2 import measured_loops
from prove_tournament_dependencies import proof


def chunk_comparisons(rtl):
    widths={name:int(msb)+1 for msb,name in re.findall(r'\b(?:wire|reg)\s+\[(\d+):0\]\s+(\w+)\s*;',rtl)}
    comparisons=re.findall(r'^assign\s+\w+\s*=\s*\(\((\w+)\s*(>=|<=|>|<)\s*(\w+)\)',rtl,re.M)
    chunks=[dict(left=left,right=right,bits=widths[left]) for left,_,right in comparisons
            if widths.get(left)==widths.get(right)==9]
    assert len(chunks)==4,'Expected four actual9bit tournament comparisons'
    assert not any(widths.get(left)==widths.get(right)==36 for left,_,right in comparisons),'Wide key comparator remains'
    return chunks


def main():
    p=argparse.ArgumentParser();p.add_argument('--job',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    state=json.loads((a.job/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['NoExport'] and state['Kernel']=='layer2'
    assert state['Part']=='xc7z015clg485-2' and abs(state['PeriodNs']-1000/150)<1e-9
    for record in json.loads((a.job/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert hashlib.sha256((a.job/'inputs'/record['Path']).read_bytes()).hexdigest().upper()==record['SHA256']
    loops=measured_loops(a.job)
    build=[l for l in loops if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*BuildTournament',l['label'])]
    banks=[l for l in loops if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*ReduceCandidateTokens',l['label'])]
    assert len(build)==1 and build[0]['II']==2
    assert len(banks)==8 and all(l['II']==1 for l in banks)
    base=a.job/'projects/layer2/solution1/syn/verilog'
    source=(a.job/'inputs/FPGA_ORB_HLS/fastv2/next/src/fastv2_hls.cpp').read_text()
    registered='impl=bram latency=2' in source
    chunks=[];dependency=None
    if registered:
        assert 'for (int node=255;node>1;--node)' in source
        directive='#pragma HLS DEPENDENCE variable=tree type=inter direction=RAW distance=2 true'
        build_source=source.split('BuildTournament:',1)[1].split('EmitStrengthOrder:',1)[0]
        assert directive in build_source and source.count('HLS DEPENDENCE variable=tree')==1
        assert 'tree[1]=tournament_winner(tree[2],tree[3]);' in build_source
        dependency=proof()
        memories=list(base.glob('*_tree_RAM_T2P_BRAM_*.v'));assert len(memories)==1
        assert re.search(r'q0_t1\s*<=\s*q0_t0\s*;',memories[0].read_text())
    else:
        path=base/'fastv2_layer2_hls_p_anonymous_namespace_consume_and_select_Pipeline_BuildTournament.v'
        chunks=chunk_comparisons(path.read_text())
    assert not (base/'fastv2_layer2_hls_p_anonymous_namespace_scan_front4_quads_Pipeline_1.v').exists()
    result=dict(status='PASS',scope='New-source C simulation/synthesis structure only; C/RTL/protocol/frame/fullroute pending',
        job=str(a.job.resolve()),tournament_build_ii=2,score_bank_ii=1,score_banks=8,actual_chunk_comparisons=chunks,
        serial_row_helper_removed=True,registered_tree_reads=registered,dependency_proof=dependency)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(f'TOURNAMENT_PROBE_STRUCTURE_PASS BuildII=2 BankII=1 registered_reads={registered} chunks={len(chunks)}')


if __name__=='__main__':main()
