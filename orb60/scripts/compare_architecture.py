"""First architecture candidate versus immutable accepted 100 MHz kernels."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from compare_hls import extract


def compare(layer, descriptor, old_layer, old_descriptor, output):
    result={'scope':'Exact HLS C/RTL and synthesis estimates only; protocol/frame/route/board pending',
            'kernels':{}}
    for kernel,new,old in [('layer2',layer,old_layer),('descriptor',descriptor,old_descriptor)]:
        before=extract(old,kernel,f'fastv2_{kernel}_hls')
        after=extract(new,kernel,f'fastv2_{kernel}_hls')
        result['kernels'][kernel]={'baseline':before,'candidate':after,
            'hls_resource_delta':{k:after['resources_hls_estimate'][k]-v for k,v in before['resources_hls_estimate'].items()}}
    stages={name:[] for name in ['compute_moments','compute_angles','compute_brief']}
    for path in (descriptor/'projects/descriptor/solution1/syn/report').glob('*_csynth.xml'):
        name=ET.parse(path).findtext('UserAssignments/TopModelName') or ''
        for stage in stages:
            if re.search('_'+stage+'$',name):stages[stage].append(name)
    result['descriptor_separate_stages']=stages
    result['descriptor_stage_gate_pass']=all(len(v)==1 for v in stages.values())
    build=[]
    for path in (layer/'projects/layer2/solution1/syn/report').glob('*_csynth.xml'):
        root=ET.parse(path);summary=root.find('PerformanceEstimates/SummaryOfLoopLatency')
        if summary is not None:
            for loop in summary:
                if re.fullmatch(r'(?:VITIS_LOOP_\d+_\d+_)*BuildTournament',loop.tag):
                    build.append({'module':root.findtext('UserAssignments/TopModelName'),
                                  'II':int(loop.findtext('PipelineII'))})
    result['tournament_build']=build
    result['tournament_gate_pass']=len(build)==1 and build[0]['II']<=2
    output.write_text(json.dumps(result,indent=2)+'\n')
    for kernel,v in result['kernels'].items():
        print('ARCHITECTURE_COMPARE',kernel,'HLS_delta',v['hls_resource_delta'],
              'cosim_max',v['baseline']['cosim_latency_cycles']['max'],'->',v['candidate']['cosim_latency_cycles']['max'])
    if not result['descriptor_stage_gate_pass'] or not result['tournament_gate_pass']:
        raise SystemExit('Architecture stage/tournament gate failed; actual evidence retained')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for arg in ['layer','descriptor','old-layer','old-descriptor','output']:
        p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();compare(a.layer,a.descriptor,a.old_layer,a.old_descriptor,a.output)
