"""Directional Slice probes: exact loops, packed keys and physical memory intent."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from compare_layer2 import measured_loops


def measure(job):
    state=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['Part']=='xc7z015clg485-2' and state['PeriodNs']==8 and state['LayerPpc']==4
    for item in json.loads((job/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert hashlib.sha256((job/'inputs'/item['Path']).read_bytes()).hexdigest().upper()==item['SHA256']
    base=job/'projects/layer2/solution1'
    x=ET.parse(base/'syn/report/fastv2_layer2_hls_csynth.xml').getroot()
    row=dict(job=str(job.resolve()),resources_hls_estimate={r.tag:int(r.text) for r in x.find('AreaEstimates/Resources')},
             timing_hls_estimate={r.tag:r.text for r in x.find('PerformanceEstimates/SummaryOfTimingAnalysis')})
    log=(job/'tool.log').read_bytes();text=log.decode('utf-16' if log.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='replace')
    assert 'LAYER2_STREAM_PASS cases=21' in text,'Missing21exact layer transactions'
    return state,base,row


def compare(baseline,jobs,output):
    _,_,old=measure(baseline);rows=[]
    for job in jobs:
        state,base,row=measure(job);mode=state['SliceCompactMode'];assert mode in (1,2,3)
        assert not state['Cosim'] and state['NoExport']
        loops=measured_loops(job);required={}
        for label,n,ii in [('ReduceCandidateTokens',8,1),('RouteCandidateBanks',1,1),('CollectBankWinners',1,1),
                           ('EmitBankWinners',8,1),('BuildTournament',1,2),('RasterQuads',1,1),
                           ('HorizontalGaussianQuads',1,1),('VerticalGaussianQuads',1,1),('ResizeSourceQuads',1,1)]:
            matches=[r for r in loops if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*'+label,r['label'])]
            assert len(matches)==n and all(r['II']==ii for r in matches),'Actual pipeline mismatch: '+label
            required[label]=matches
        selector=(base/'syn/verilog/fastv2_layer2_hls_p_anonymous_namespace_consume_and_select.v').read_text()
        banks=re.findall(r'\b\w+_tree_RAM_T2P_BRAM_1R1W\s*#\((.*?)\)\s*(tree(?:_1)?_U)\s*\(',selector,re.S)
        width=38 if mode==1 else 36
        assert {name for _,name in banks}=={'tree_U','tree_1_U'}
        assert all(re.search(r'\.DataWidth\(\s*'+str(width)+r'\s*\)',body) for body,_ in banks),'Actual tree width changed'
        reducers=list((base/'syn/verilog').glob('*reduce_score_bank_*_s.v'))
        assert len(reducers)==8,'Missing eight independent score banks'
        memory='BRAM' if mode==3 else 'LUTRAM'
        assert all('_points_RAM_S2P_'+memory+'_1R1W' in p.read_text() for p in reducers),'Payload storage mapping differs from requested architecture'
        top=(base/'syn/verilog/fastv2_layer2_hls.v').read_text()
        for kind,expected in [('DATA',64),('ADDR',32)]:
            values=re.findall(r'parameter\s+C_M_AXI_(\w+)_'+kind+r'_WIDTH\s*=\s*(\d+)',top)
            assert len(values)==4 and all(int(v)==expected for _,v in values)
        row.update(mode=mode,key_bits=width,payload_memory=memory,required_loops=required,
                   resource_delta={k:v-old['resources_hls_estimate'][k] for k,v in row['resources_hls_estimate'].items()})
        rows.append(row)
    output.write_text(json.dumps(dict(status='PASS',scope='Candidate exact CSim, real II and generated memory structure; co-sim/fullroute/frame/board separate',baseline=old,candidates=rows),indent=2)+'\n')
    for row in rows:print('SLICE_MODE',row['mode'],'key_bits',row['key_bits'],'payload',row['payload_memory'],'HLS_DELTA',row['resource_delta'])
    print('SLICE_COMPACT_PROBES_PASS')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--jobs',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();compare(a.baseline,a.jobs,a.output)
