"""Compact synthesis/co-simulation comparison; never labels estimates as route."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def extract(job, kernel, top):
    root = job / f'projects/{kernel}/solution1'
    xml = ET.parse(root / f'syn/report/{top}_csynth.xml').getroot()
    resources = {p.tag: int(p.text) for p in xml.find('AreaEstimates/Resources')}
    clock = xml.find('PerformanceEstimates/SummaryOfTimingAnalysis')
    text = (root / f'sim/report/{top}_cosim.rpt').read_text()
    assert re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|', text)
    latency = re.search(r'\|\s*Verilog\s*\|\s*Pass\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)', text)
    raw = (job / 'tool.log').read_bytes()
    log = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='replace')
    start = log.find(f'ORB60_STAGE_BEGIN kernel={kernel}')
    end = log.find(f'ORB60_STAGE_DONE kernel={kernel}', start)
    if start >= 0:
        log = log[start:end if end >= 0 else None]
    loops = {name: {'II': int(ii), 'depth': int(depth)} for ii, depth, name in re.findall(
        r'Final II = (\d+), Depth = (\d+), loop [\'\"]([^\'\"]+)', log)}
    rtl = (root / f'syn/verilog/{top}.v').read_text()
    buses = {name: int(value) for name, value in re.findall(r'parameter\s+C_M_AXI_(\w+)_DATA_WIDTH\s*=\s*(\d+)', rtl)}
    return dict(job=str(job), resources_hls_estimate=resources,
                timing_hls_estimate={p.tag: p.text for p in clock},
                cosim_latency_cycles=dict(zip(('min', 'avg', 'max'), map(int, latency.groups()))),
                pipelined_loops=loops, axi_data_widths=buses)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--front', type=Path, required=True)
    p.add_argument('--resize', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--previous-front', type=Path)
    a = p.parse_args()
    result = {'evidence_scope': 'HLS estimates and accepted C/RTL transactions; not routed timing or board FPS', 'kernels': {}}
    for k, job, top in (('front', a.front, 'fastv2_front64_hls'), ('resize', a.resize, 'fastv2_resize_hls')):
        old = extract(a.baseline, k, f'fastv2_{k}_hls')
        new = extract(job, k, top)
        delta = {name: new['resources_hls_estimate'][name] - value for name, value in old['resources_hls_estimate'].items()}
        result['kernels'][k] = dict(baseline=old, optimized=new, resource_delta=delta)
        print(f'ORB60_COMPARE {k} resource_delta={delta} cosim_max_cycles={old["cosim_latency_cycles"]["max"]}->{new["cosim_latency_cycles"]["max"]}')
    if a.previous_front:
        result['previous_front'] = extract(a.previous_front, 'front', 'fastv2_front64_hls')
    a.output.write_text(json.dumps(result, indent=2) + '\n')
