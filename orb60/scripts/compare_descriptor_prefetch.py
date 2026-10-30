"""Check manual row-request structure and compare retained HLS RTL evidence.

Adapter configuration is not measured outstanding occupancy or frame speed.
Those are subsequent randomized/native shared-DDR gates.
"""
import argparse
import json
from pathlib import Path
import re
from compare_descriptor_width_probes import measure
from compare_hls import extract


def registers(job):
    source=(job/'projects/descriptor/solution1/impl/ip/drivers/fastv2_descriptor_hls_v1_0/src/xfastv2_descriptor_hls_hw.h').read_text()
    return dict(re.findall(r'#define\s+(XFASTV2_DESCRIPTOR_HLS_CONTROL_(?:ADDR|BITS)_\w+)\s+(\w+)',source))


def check(baseline,jobs,output):
    old=measure(baseline);old['rtl']=extract(baseline,'descriptor','fastv2_descriptor_hls')
    old_registers=registers(baseline)
    assert old_registers and old['mode']==0
    manifest=None;vector_manifest=None;rows=[]
    for job,depth in zip(jobs,(2,4,8)):
        state=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
        assert state['Cosim'] and not state['NoExport'] and state['DescriptorPrefetch']==depth
        row=measure(job);assert row['mode']==0
        row['prefetch_requests']=depth;row['rtl']=extract(job,'descriptor','fastv2_descriptor_hls')
        sources=json.loads((job/'source_manifest.json').read_text(encoding='utf-8-sig'))
        vectors=json.loads((job/'descriptor_vectors/vectors.json').read_text())['sha256']
        if manifest is None:manifest=sources;vector_manifest=vectors
        assert sources==manifest and vectors==vector_manifest,'Prefetch variants must use identical frozen inputs'
        assert registers(job)==old_registers,'Manual-burst register map changed'
        top=(job/'projects/descriptor/solution1/syn/verilog/fastv2_descriptor_hls.v').read_text()
        configured={}
        for port in (0,1):
            body=re.search(r'fastv2_descriptor_hls_gmem'+str(port)+r'_m_axi\s*#\((.*?)\)\s*gmem'+str(port)+r'_m_axi_U\s*\(',top,re.S)
            assert body,'Missing actual patch-port AXI adapter'
            outstanding=re.search(r'\.NUM_READ_OUTSTANDING\(\s*(\d+)\s*\)',body[1])
            assert outstanding and int(outstanding[1])==depth
            configured['gmem'+str(port)]=int(outstanding[1])
        dataflow=(job/'projects/descriptor/solution1/syn/verilog/fastv2_descriptor_hls_p_anonymous_namespace_descriptor_dataflow.v').read_text()
        actors=re.findall(r'^(\w+)\s+(\w+)\s*\(\s*\n(.*?)\n\);',dataflow,re.M|re.S)
        stages={}
        for name in ('issue_raw_requests','issue_blur_requests','load_raw','load_blur'):
            found=[dict(module=module,instance=instance) for module,instance,_ in actors
                   if re.search(r'_'+name+r'_U\d+$',instance)]
            assert len(found)==1,'Missing independent DATAFLOW actor: '+name
            stages[name]=found[0]
        row['separate_request_receive_actors']=stages
        row['adapter_configured_outstanding']=configured
        row['required_transfer_loops']={}
        for name in ('IssueRawPatchRows','IssueBlurPatchRows','ReceiveRawRowWords','ReceiveBlurRowWords'):
            matches=[v for k,v in row['rtl']['pipelined_loops'].items() if k==name or k.endswith('_'+name)]
            assert len(matches)==1 and matches[0]['II']==1,'Manual row transfer is not II=1: '+name
            row['required_transfer_loops'][name]=matches[0]
        row['resource_delta']={k:v-old['resources_hls_estimate'][k] for k,v in row['resources_hls_estimate'].items()}
        rows.append(row)
    result=dict(scope='38 independent exact CSim and Verilog co-sim transactions per candidate, actual request/receive actors and adapter configuration; randomized AXI, real occupancy, frame and route pending',baseline=old,candidates=rows)
    output.write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print('PREFETCH',row['prefetch_requests'],'resources',row['resource_delta'],'cosim',row['rtl']['cosim_latency_cycles'])
    print('DESCRIPTOR_PREFETCH_HLS_GATES_PASS')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--jobs',type=Path,nargs=3,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();check(a.baseline,a.jobs,a.output)
