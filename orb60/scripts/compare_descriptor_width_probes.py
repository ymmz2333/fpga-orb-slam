"""Read fast exact-CSim/synthesis experiments without requiring or claiming RTL pass."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def measure(job,probe=False):
    state=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['Kernel']=='descriptor' and state['PeriodNs']==10
    assert state['Part']=='xc7z015clg485-2'
    if probe:assert not state['Cosim'] and state['NoExport'] and state['DescriptorWidthMode'] in (1,2)
    for item in json.loads((job/'source_manifest.json').read_text(encoding='utf-8-sig')):
        assert hashlib.sha256((job/'inputs'/item['Path']).read_bytes()).hexdigest().upper()==item['SHA256']
    vectors=json.loads((job/'descriptor_vectors/vectors.json').read_text())
    for name,digest in vectors['sha256'].items():
        assert hashlib.sha256((job/'descriptor_vectors'/name).read_bytes()).hexdigest()==digest
    raw=(job/'tool.log').read_bytes()
    log=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='replace')
    assert 'DESCRIPTOR_STREAM_PASS cases=38' in log
    xml=ET.parse(job/'projects/descriptor/solution1/syn/report/fastv2_descriptor_hls_csynth.xml').getroot()
    resources={x.tag:int(x.text) for x in xml.find('AreaEstimates/Resources')}
    timing={x.tag:x.text for x in xml.find('PerformanceEstimates/SummaryOfTimingAnalysis')}
    loops=[]
    for file in (job/'projects/descriptor/solution1/syn/report').glob('*_csynth.xml'):
        root=ET.parse(file).getroot();latencies=root.find('PerformanceEstimates/SummaryOfLoopLatency')
        if latencies is None:continue
        for loop in latencies:
            ii=loop.findtext('PipelineII')
            if ii is not None:loops.append(dict(label=loop.tag,II=int(ii)))
    required={}
    for name in ('MomentCenterRow','MomentSymmetricPairs','BriefBits','CountDescriptorCycles'):
        matches=[x for x in loops if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*'+name,x['label'])]
        required[name]=matches
        assert len(matches)==1 and matches[0]['II']==1
    rtl=(job/'projects/descriptor/solution1/syn/verilog/fastv2_descriptor_hls.v').read_text()
    dataflow=(job/'projects/descriptor/solution1/syn/verilog/fastv2_descriptor_hls_p_anonymous_namespace_descriptor_dataflow.v').read_text()
    fifo_widths={}
    for name in ('moments','angles'):
        widths=re.findall(r'\b\w+_fifo_w(\d+)_d2_\w+\s+'+name+r'_U\s*\(',dataflow)
        assert len(widths)==1,'Missing actual packed '+name+' FIFO'
        fifo_widths[name]=int(widths[0])
    assert fifo_widths==({'moments':202,'angles':234} if state.get('DescriptorWidthMode',0) else {'moments':224,'angles':256})
    for kind,width in [('DATA',64),('ADDR',32)]:
        buses=re.findall(r'parameter\s+C_M_AXI_(GMEM\d)_'+kind+r'_WIDTH\s*=\s*(\d+)',rtl)
        assert len(buses)==4 and all(int(v)==width for _,v in buses)
    return dict(job=str(job.resolve()),mode=state.get('DescriptorWidthMode',0),resources_hls_estimate=resources,
                timing_hls_estimate=timing,required_loops=required,csim_exact_transactions=38,
                rtl_cosim_verified=bool(state['Cosim']),no_export=state.get('NoExport',False),actual_fifo_widths=fifo_widths)


def compare(baseline,moment,cordic,output):
    old=measure(baseline);one=measure(moment,True);two=measure(cordic,True)
    assert one['mode']==1 and two['mode']==2
    manifests=[]
    for root in (moment,cordic):
        manifests.append({x['Path']:x['SHA256'] for x in json.loads((root/'source_manifest.json').read_text(encoding='utf-8-sig'))})
    assert manifests[0]==manifests[1], 'Incremental width probes must use identical source snapshots'
    for row,reference in ((one,old),(two,one)):
        row['incremental_delta']={k:v-reference['resources_hls_estimate'][k] for k,v in row['resources_hls_estimate'].items()}
        row['baseline_delta']={k:v-old['resources_hls_estimate'][k] for k,v in row['resources_hls_estimate'].items()}
    result=dict(scope='38 independent exact CSim transactions and HLS estimates only; RTL co-sim/protocol/frame/route pending',
                baseline=old,moment21=one,moment21_cordic43_z34=two)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print('DESCRIPTOR_WIDTH_PROBE_PASS; exact CSim and real II/interface only')
    for row in (one,two):print('MODE',row['mode'],'incremental',row['incremental_delta'],'baseline',row['baseline_delta'])


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('baseline','moment','cordic','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();compare(a.baseline,a.moment,a.cordic,a.output)
