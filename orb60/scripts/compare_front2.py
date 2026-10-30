"""Compare accepted 1PPC/2PPC FAST jobs; keep throughput gates explicit."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from compare_hls import extract


def resolve_loop(loops, name):
    # HLS prefixes the source label when it flattens an enclosing loop nest.
    # Accept only that documented-in-report shape, with a unique match.
    pattern = re.compile(r'(?:VITIS_LOOP_\d+_\d+_)*' + re.escape(name))
    matches = [(label, value) for label, value in loops.items() if pattern.fullmatch(label)]
    if len(matches) != 1:
        raise ValueError(f'Expected one reported loop for {name}; found {[m[0] for m in matches]}')
    return matches[0]


def loop_proof(job, loops, name):
    label, value = resolve_loop(loops, name)
    report_dir = job / 'projects/front2/solution1/syn/report'
    reports = list(report_dir.glob(f'*_Pipeline_{label}_csynth.xml'))
    if len(reports) != 1:
        raise ValueError(f'Expected one pipeline XML report for {label}; found {len(reports)}')
    report = reports[0]
    xml = ET.parse(report).getroot()
    ii = xml.findtext(f'PerformanceEstimates/SummaryOfLoopLatency/{label}/PipelineII')
    if ii is None or int(ii) != value['II']:
        raise ValueError(f'Log/XML II mismatch for {label}: log={value["II"]}, XML={ii}')
    return {'reported_label': label, 'II': int(ii), 'depth': value['depth'], 'xml_report': str(report)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--front2', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    old = extract(args.previous, 'front', 'fastv2_front64_hls')
    new = extract(args.front2, 'front2', 'fastv2_front2_hls')
    required = ('UnpackPairs', 'RasterPairs', 'MergePairs', 'ReduceCandidateTokens')
    proof = {name: loop_proof(args.front2, new['pipelined_loops'], name) for name in required}
    actual = {name: value['II'] for name, value in proof.items()}
    delta = {name: new['resources_hls_estimate'][name] - value
             for name, value in old['resources_hls_estimate'].items()}
    result = {
        'evidence_scope': 'HLS estimates and C/RTL co-simulation; no route or board FPS claim',
        'previous_1ppc': old, 'front2_2ppc': new, 'resource_delta': delta,
        'transactions': {'previous': 11, 'front2': 16,
                         'comparison': 'First 11 inputs identical; five added odd-width/all-level cases'},
        'required_loop_ii': actual,
        'loop_evidence': proof,
        'throughput_gate_pass': all(ii == 1 for ii in actual.values()),
    }
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f'ORB60_FRONT2_COMPARE II={actual} resource_delta={delta}')
    print(f'ORB60_FRONT2_COSIM_MAX {old["cosim_latency_cycles"]["max"]}->{new["cosim_latency_cycles"]["max"]}')
    if not result['throughput_gate_pass']:
        raise SystemExit('2PPC pipeline target failed: every required loop must have measured II=1')


if __name__ == '__main__':
    main()
