"""Exact structure/clock/register gates for the bounded frequency pair."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from compare_layer2 import measured_loops
from check_tournament_probe import chunk_comparisons
from prove_tournament_dependencies import proof as dependency_proof

def checked(job,kernel):
    state=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['Cosim'] and state['Kernel']==kernel
    assert state['Part']=='xc7z015clg485-2' and 5<=state['PeriodNs']<=8
    for entry in json.loads((job/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert hashlib.sha256((job/'inputs'/entry['Path']).read_bytes()).hexdigest().upper()==entry['SHA256']
    return state,job/f'projects/{kernel}/solution1'

def registers(base,kernel):
    path=base if base.is_file() else base/f'impl/ip/drivers/fastv2_{kernel}_hls_v1_0/src/xfastv2_{kernel}_hls_hw.h'
    return dict(re.findall(r'#define\s+(XFASTV2_\w+_HLS_CONTROL_\w+)\s+(0x[\da-fA-F]+|\d+)\b',path.read_text()))

def main():
    p=argparse.ArgumentParser();p.add_argument('--pair',type=Path,required=True)
    p.add_argument('--baseline-layer',type=Path);p.add_argument('--baseline-descriptor',type=Path)
    p.add_argument('--baseline-layer-registers',type=Path);p.add_argument('--baseline-descriptor-registers',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not (a.baseline_layer or a.baseline_layer_registers) or not (a.baseline_descriptor or a.baseline_descriptor_registers):
        p.error('Both independent prior register definitions are required')
    pair=json.loads((a.pair/'status.json').read_text(encoding='utf-8-sig'))
    assert pair['State']=='SUCCEEDED' and pair['Stage']=='C_RTL_PAIR_COMPLETE'
    layer,lb=checked(Path(pair['LayerHlsJob']),'layer2')
    desc,db=checked(Path(pair['DescriptorHlsJob']),'descriptor')
    assert abs(layer['PeriodNs']-desc['PeriodNs'])<1e-9
    assert layer['LayerPpc']==4 and layer['SliceCompactMode']==2
    assert desc['DescriptorWidthMode']==2 and desc['DescriptorPrefetch']==8 and desc['DescriptorPatch32']
    assert desc['DescriptorMomentFusion']==desc['DescriptorFastQuantize']==1
    loops=measured_loops(Path(pair['LayerHlsJob']))
    build=[row for row in loops if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*BuildTournament',row['label'])]
    assert len(build)==1 and build[0]['II']==2
    selector=(lb/'syn/verilog/fastv2_layer2_hls_p_anonymous_namespace_consume_and_select.v').read_text()
    banks=re.findall(r'\b(\w+_tree_RAM_T2P_BRAM_(?:1R1W|2R1W))\s*#\((.*?)\)\s*(tree(?:_1)?_U)\s*\(',selector,re.S)
    assert {name for _,_,name in banks}=={'tree_U','tree_1_U'}
    assert all(re.search(r'\.DataWidth\(\s*36\s*\)',body) for _,body,_ in banks)
    registered_tree='impl=bram latency=2' in (Path(pair['LayerHlsJob'])/'inputs/FPGA_ORB_HLS/fastv2/next/src/fastv2_hls.cpp').read_text()
    if registered_tree:
        source=(Path(pair['LayerHlsJob'])/'inputs/FPGA_ORB_HLS/fastv2/next/src/fastv2_hls.cpp').read_text()
        assert 'for (int node=255;node>1;--node)' in source
        build_source=source.split('BuildTournament:',1)[1].split('EmitStrengthOrder:',1)[0]
        assert '#pragma HLS DEPENDENCE variable=tree type=inter direction=RAW distance=2 true' in build_source
        assert 'tree[1]=tournament_winner(tree[2],tree[3]);' in build_source
        dependency_proof()
        for module,_,_ in banks:
            actual=(lb/'syn/verilog'/f'{module}.v').read_text()
            assert re.search(r'q0_t1\s*<=\s*q0_t0\s*;',actual),'Missing actual second read register'
            assert re.search(r'q0_t0\s*<=\s*ram\[address0\]\s*;',actual),'Missing actual RAM read stage'
    balanced_chunks='CompareTournamentChunks:' in (Path(pair['LayerHlsJob'])/'inputs/FPGA_ORB_HLS/fastv2/next/src/banked_grid.hpp').read_text()
    key_chunks=[]
    if balanced_chunks:
        key_chunks=chunk_comparisons((lb/'syn/verilog/fastv2_layer2_hls_p_anonymous_namespace_consume_and_select_Pipeline_BuildTournament.v').read_text())
    reducers=list((lb/'syn/verilog').glob('*reduce_score_bank_*_s.v'))
    assert len(reducers)==8 and all('_points_RAM_S2P_LUTRAM_1R1W' in path.read_text() for path in reducers)
    distributed='CompareLocalScores:' in (Path(pair['LayerHlsJob'])/'inputs/FPGA_ORB_HLS/fastv2/next/src/banked_grid.hpp').read_text()
    local_comparators=[]
    if distributed:
        pipelines=list((lb/'syn/verilog').glob('*reduce_score_bank_*_Pipeline_ReduceCandidateTokens.v'))
        assert len(pipelines)==8
        for path in pipelines:
            count=len(re.findall(r'^assign\s+icmp_\w+\s*=.*score_\w+\s*>\s*scores\w*',path.read_text(),re.M))
            assert count==26,'Actual per-cell score comparators missing: '+path.name
            local_comparators.append(dict(module=path.stem,comparators=count))
    parallel_rows='ResetFastRowWindow:' in (Path(pair['LayerHlsJob'])/'inputs/FPGA_ORB_HLS/fastv2/next/src/front4_stream.hpp').read_text()
    if parallel_rows:
        # The measured original helper took72cycles for its70-byte row memset.
        # Assert that the generated initialization loop really disappeared.
        assert not (lb/'syn/verilog/fastv2_layer2_hls_p_anonymous_namespace_scan_front4_quads_Pipeline_1.v').exists()
    qxml=ET.parse(db/'syn/report/p_anonymous_namespace_quantize_angle_csynth.xml').getroot()
    summary=qxml.find('PerformanceEstimates/SummaryOfOverallLatency')
    assert int(summary.findtext('Interval-min'))==int(summary.findtext('Interval-max'))==1
    assert not any('QuantizeSearch' in path.read_text() for path in (db/'syn/verilog').glob('*.v'))
    top=(db/'syn/verilog/fastv2_descriptor_hls.v').read_text()
    dataflow=(db/'syn/verilog/fastv2_descriptor_hls_p_anonymous_namespace_descriptor_dataflow.v').read_text()
    actors=re.findall(r'^(\w+)\s+(\w+)\s*\(\s*\n(.*?)\n\);',dataflow,re.M|re.S)
    for name in ('issue_raw_requests','issue_blur_requests','receive_raw_moments','load_blur','compute_angles','compute_brief'):
        assert len([instance for _,instance,_ in actors if re.search('_'+name+r'_U\d+$',instance)])==1,name
    assert 'raw_blocks_U' not in dataflow and not re.search(r'_(?:load_raw|compute_moments)_U\d+',dataflow)
    raw_source=(Path(pair['DescriptorHlsJob'])/'inputs/FPGA_ORB_HLS/fastv2/next/src/descriptor_hls.cpp').read_text()
    flat_raw='while(row<31)' in raw_source
    if flat_raw:
        assert 'ReceiveRawMomentRows:' not in raw_source
        receive=ET.parse(db/'syn/report/p_anonymous_namespace_receive_raw_moments_csynth.xml').getroot()
        assert not any('ReceiveRawMomentRows' in element.tag for element in receive.iter())
    for port in (0,1):
        adapter=re.search(r'fastv2_descriptor_hls_gmem'+str(port)+r'_m_axi\s*#\((.*?)\)\s*gmem'+str(port)+r'_m_axi_U\s*\(',top,re.S)
        assert adapter and re.search(r'\.NUM_READ_OUTSTANDING\(\s*8\s*\)',adapter[1])
    for kernel,base,prior,header in [('layer2',lb,a.baseline_layer,a.baseline_layer_registers),('descriptor',db,a.baseline_descriptor,a.baseline_descriptor_registers)]:
        baseline=header if header else prior/f'projects/{kernel}/solution1'
        assert registers(base,kernel)==registers(baseline,kernel),'MMIO numeric definitions changed'
        rtl=(base/f'syn/verilog/fastv2_{kernel}_hls.v').read_text()
        for kind,width in [('DATA',64),('ADDR',32)]:
            values=re.findall(r'parameter\s+C_M_AXI_(\w+)_'+kind+r'_WIDTH\s*=\s*(\d+)',rtl)
            assert len(values)==4 and all(int(v)==width for _,v in values)
    result=dict(status='PASS',scope='Fresh C/RTL + real II/structure/clock/register evidence; protocol/frame/fullroute/board separate',
        nominal_frequency_mhz=1000/layer['PeriodNs'],period_ns=layer['PeriodNs'],simulation_period_ps=round(layer['PeriodNs']*1000),
        quantizer_latency_cycles=int(summary.findtext('Worst-caseLatency')),quantizer_ii=1,tournament_bits=36,
        tournament_build_ii=2,score_banks=8,mmio_numerically_unchanged=True,
        distributed_score_comparisons=distributed,actual_local_comparators=local_comparators,
        descriptor_reused_from=pair.get('DescriptorReusedFrom'),parallel_row_initialization=parallel_rows,
        layer_reused_from=pair.get('LayerReusedFrom'),serial_72cycle_row_helper_removed=parallel_rows,
        registered_tournament_reads=registered_tree,flattened_raw_receive=flat_raw,
        balanced_tournament_chunks=balanced_chunks,actual_tournament_chunk_comparisons=key_chunks)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(f'FREQUENCY_PAIR_STRUCTURE_PASS nominal_mhz={result["nominal_frequency_mhz"]:g} quantizer_ii=1 key_bits=36 banks=8 distributed={distributed} local_comparators={[r["comparators"] for r in local_comparators]} MMIO=unchanged')

if __name__=='__main__':main()
