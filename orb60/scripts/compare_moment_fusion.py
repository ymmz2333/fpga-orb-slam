"""Gate candidate-only fused receiver probes, without claiming RTL or route pass."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def inputs(job):
    manifest=json.loads((job/'source_manifest.json').read_text(encoding='utf-8-sig'))
    for item in manifest:
        assert hashlib.sha256((job/'inputs'/item['Path']).read_bytes()).hexdigest().upper()==item['SHA256']
    vectors=json.loads((job/'descriptor_vectors/vectors.json').read_text())
    for name,digest in vectors['sha256'].items():
        assert hashlib.sha256((job/'descriptor_vectors'/name).read_bytes()).hexdigest()==digest
    return manifest,vectors


def measure(job):
    state=json.loads((job/'status.json').read_text(encoding='utf-8-sig'))
    assert state['State']=='SUCCEEDED' and state['Kernel']=='descriptor' and state['Part']=='xc7z015clg485-2'
    base=job/'projects/descriptor/solution1'
    root=ET.parse(base/'syn/report/fastv2_descriptor_hls_csynth.xml').getroot()
    resources={p.tag:int(p.text) for p in root.find('AreaEstimates/Resources')}
    raw=(job/'tool.log').read_bytes()
    log=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='replace')
    assert 'DESCRIPTOR_STREAM_PASS cases=38' in log
    manifest,vectors=inputs(job)
    return state,base,manifest,vectors,dict(job=str(job.resolve()),resources_hls_estimate=resources,
        timing_hls_estimate={p.tag:p.text for p in root.find('PerformanceEstimates/SummaryOfTimingAnalysis')})


def compare(baseline,jobs,output):
    old_state,old_base,_,old_vectors,old=measure(baseline)
    assert old_state['Cosim'] and not old_state.get('DescriptorMomentFusion',0)
    assert re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|',(old_base/'sim/report/fastv2_descriptor_hls_cosim.rpt').read_text())
    assert 1 <= len(jobs) <= 2
    rows=[];manifest=None;seen=set()
    for job in jobs:
        state,base,source,vectors,row=measure(job)
        mode=state['DescriptorMomentFusion'];assert mode in (1,2) and mode not in seen;seen.add(mode)
        assert state['PeriodNs']==old_state['PeriodNs'] and state['DescriptorWidthMode']==2
        if state['Cosim']:
            assert not state['NoExport']
            report=(base/'sim/report/fastv2_descriptor_hls_cosim.rpt').read_text()
            latency=re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)',report)
            assert latency,'Missing exact C/RTL co-sim pass'
            row['cosim_latency_cycles']=dict(zip(('min','avg','max'),map(int,latency.groups())))
            header='impl/ip/drivers/fastv2_descriptor_hls_v1_0/src/xfastv2_descriptor_hls_hw.h'
            def registers(path):
                return dict(re.findall(r'#define\s+(XFASTV2_DESCRIPTOR_HLS_CONTROL_(?:ADDR|BITS)_\w+)\s+(\w+)',path.read_text()))
            old_regs=registers(old_base/header);new_regs=registers(base/header)
            assert old_regs and new_regs==old_regs,'Descriptor MMIO map changed'
            row['register_map_unchanged']=True
        else:
            assert state['NoExport'],'Unverified exported candidate'
        assert state['DescriptorPrefetch']==8 and state['DescriptorPatch32']
        assert vectors==old_vectors,'Fusion must use identical independent record/byte oracles'
        if manifest is None:manifest=source
        assert source==manifest,'Mapping alternatives must use identical frozen source bytes'
        top=(base/'syn/verilog/fastv2_descriptor_hls.v').read_text()
        for kind,width in [('DATA',64),('ADDR',32)]:
            buses=re.findall(r'parameter\s+C_M_AXI_(GMEM\d)_'+kind+r'_WIDTH\s*=\s*(\d+)',top)
            assert len(buses)==4 and all(int(v)==width for _,v in buses)
        for port in (0,1):
            adapter=re.search(r'fastv2_descriptor_hls_gmem'+str(port)+r'_m_axi\s*#\((.*?)\)\s*gmem'+str(port)+r'_m_axi_U\s*\(',top,re.S)
            assert adapter and re.search(r'\.NUM_READ_OUTSTANDING\(\s*8\s*\)',adapter[1]),'Patch adapter lost eight request credits'
        dataflow=(base/'syn/verilog/fastv2_descriptor_hls_p_anonymous_namespace_descriptor_dataflow.v').read_text()
        actors=re.findall(r'^(\w+)\s+(\w+)\s*\(\s*\n(.*?)\n\);',dataflow,re.M|re.S)
        stages={}
        for name in ('issue_raw_requests','issue_blur_requests','receive_raw_moments','load_blur','compute_angles','compute_brief'):
            matches=[dict(module=m,instance=i) for m,i,_ in actors if re.search('_'+name+r'_U\d+$',i)]
            assert len(matches)==1,'Missing independent DATAFLOW actor: '+name
            stages[name]=matches[0]
        assert 'raw_blocks_U' not in dataflow and not re.search(r'_(?:load_raw|compute_moments)_U\d+',dataflow), 'Old raw-patch storage/compute actor was not eliminated'
        loops=[]
        for file in (base/'syn/report').glob('*_csynth.xml'):
            summary=ET.parse(file).getroot().find('PerformanceEstimates/SummaryOfLoopLatency')
            if summary is None:continue
            for loop in summary:
                ii=loop.findtext('PipelineII')
                if ii is not None:loops.append(dict(label=loop.tag,II=int(ii)))
        required={}
        for name in ('IssueRawPatchRows','IssueBlurPatchRows','ReceiveRawMomentWords','ReceiveBlurRowWords','BriefBits','CountDescriptorCycles'):
            matches=[v for v in loops if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*'+name,v['label'])]
            required[name]=matches
            assert len(matches)==1 and matches[0]['II']==1,'Real pipeline failed: '+name
        row.update(mode=mode,rtl_cosim_verified=bool(state['Cosim']),required_loops=required,actual_stages=stages,raw_block_storage_eliminated=True,
            resource_delta={k:v-old['resources_hls_estimate'][k] for k,v in row['resources_hls_estimate'].items()})
        rows.append(row)
    result=dict(status='PASS',scope='Independent 38-record exact CSim, real II=1 and generated architecture; C/RTL/MMIO only where explicitly marked; protocol/frame/route/board separate',baseline=old,candidates=rows)
    output.write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print('FUSION_MODE',row['mode'],'delta',row['resource_delta'],'clock_estimate',row['timing_hls_estimate'])
    print('RAW_MOMENT_FUSION_PROBES_PASS')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--jobs',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();compare(a.baseline,a.jobs,a.output)
