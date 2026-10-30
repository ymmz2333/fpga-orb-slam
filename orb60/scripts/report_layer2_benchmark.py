"""Separate measured layer cycles from an explicitly conditional PS projection."""
import argparse
import json
from pathlib import Path
import re


def read_text(path):
    data = path.read_bytes()
    return data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')


def projection(pl_ms, backend_ms, cache_ms, control_ms):
    # Existing PS(n)/PL(n+1) scheduling. Cache/control stay outside overlap.
    overlap_ms = pl_ms[0] + sum(max(pl_ms[i+1], backend_ms[i]) for i in range(7)) + backend_ms[7]
    total_ms = overlap_ms + cache_ms + control_ms
    return dict(backend_ms_per_level=backend_ms, backend_total_ms=sum(backend_ms),
                complete_frame_estimate_ms=total_ms, complete_frame_estimate_fps=1000/total_ms,
                sequential_estimate_ms=sum(pl_ms)+sum(backend_ms)+cache_ms+control_ms)


def report(job, archive, output):
    vectors = json.loads((job/'vectors/vectors.json').read_text())
    native = read_text(job/'native.log')
    tool = read_text(job/'tool.log')
    if 'LAYER2_BENCH_EXACT_PASS cases=24' not in native:
        raise ValueError('Missing native exact acceptance')
    rtl_proofs = re.findall(r'LAYER2_BENCH_LAYER frame=(\d+) level=(\d+) cycles=(\d+) candidates=(\d+) selected=(\d+)', tool)
    if len(rtl_proofs) < 24 or 'LAYER2_BENCH_EXACT_PASS cases=24' not in tool:
        raise ValueError('Missing complete RTL benchmark acceptance')
    rtl_proofs = [tuple(map(int, row)) for row in rtl_proofs[-24:]]
    # The last pass must be the RTL wrapper, not native Csim's constant cycle=1.
    if any(row[2] < 1000 for row in rtl_proofs):
        raise ValueError('No actual RTL cycle counters')
    rpt = job/'projects/layer2/solution1/sim/report/verilog/result.transaction.rpt'
    latency = [tuple(map(int, row)) for row in re.findall(r'transaction\s+(\d+):\s+(\d+)', read_text(rpt))]
    if len(latency) != 24 or [i for i, _ in latency] != list(range(24)):
        raise ValueError('Stale/incomplete transaction latency report')
    if (job/'rtl_manifest_before.json').read_bytes() != (job/'rtl_manifest_after.json').read_bytes():
        raise ValueError('Generated RTL changed')
    historic = archive/'board_profile_Production_Pipeline_100_quiet_20261010_161439_138.log'
    old = read_text(historic)
    backend = [float(value) for value in re.findall(r'level=\d+ front_ms=[^\n]+ps_backend_ms=([0-9.]+)', old)]
    if len(backend) != 8:
        raise ValueError('Missing historical per-layer backend times')
    cache = float(re.search(r'cache_ms=([0-9.]+)', old).group(1))
    config = float(re.search(r'config_ms=([0-9.]+)', old).group(1))
    residual = float(re.search(r'other_ms=([0-9.]+)', old).group(1))
    old_counts = (64,45,44,38,29,24,19,17)
    frames = []
    for frame in range(3):
        cases = vectors['cases'][frame*8:frame*8+8]
        measured = rtl_proofs[frame*8:frame*8+8]
        pl_ms = []
        for i, (case, measured_row) in enumerate(zip(cases, measured)):
            if measured_row[:2] != (frame,i) or measured_row[3:] != (case['candidates'],case['selected']):
                raise ValueError('RTL metadata differs from independent golden')
            pl_ms.append(latency[frame*8+i][1]/100000)
        projected_backend = [backend[i]*cases[i]['selected']/old_counts[i] for i in range(8)]
        frames.append(dict(frame=frame, label=cases[0]['label'],
                           selected=sum(c['selected'] for c in cases),
                           candidates=sum(c['candidates'] for c in cases),
                           layer_latency_cycles=[n for _,n in latency[frame*8:frame*8+8]],
                           dataflow_cycles=[row[2] for row in measured],
                           frontend_ms=sum(pl_ms), frontend_equivalent_fps=1000/sum(pl_ms),
                           unchanged_arm_projection=projection(pl_ms,projected_backend,cache,config+residual)))
    max_counts = (204,165,140,117,105,87,70,54)
    result = dict(scope='24 exact C/RTL transactions on unchanged accepted layer RTL, assumed 100 MHz',
                  frequency_mhz=100, frames=frames,
                  historical_ps_log=str(historic), historical_selected_per_level=old_counts,
                  hypothetical_942_point_projection=projection(
                      [n/100000 for n in frames[1]['layer_latency_cycles']],
                      [backend[i]*max_counts[i]/old_counts[i] for i in range(8)],cache,config+residual),
                  projection_assumptions=[
                      'PS source unmodified; the new layer control interface is not yet integrated into PS',
                      'Historical ARM time per point scales linearly within each level; cache locality is not measured',
                      'PS descriptors(n) overlap layer(n+1) as in historical pipeline',
                      'Historical whole-image cache/control overhead retained without optimization',
                      'No physical DDR contention/PS delay/temperature effect is measured by this cosim',
                      'Frontend FPS is the reciprocal of eight summed layer latencies, not complete ORB FPS',
                      'Single samples do not establish P99/max or continuous video performance'],
                  physical_board_fps_verified=False, ps_modified=False, rtl_unchanged=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    for frame in frames:
        estimate=frame['unchanged_arm_projection']
        print(f'LAYER2_BENCH_MEASURED label={frame["label"]} selected={frame["selected"]} '
              f'frontend_ms={frame["frontend_ms"]:.5f} frontend_fps={frame["frontend_equivalent_fps"]:.2f}')
        print(f'LAYER2_BENCH_MODEL label={frame["label"]} complete_ms={estimate["complete_frame_estimate_ms"]:.3f} '
              f'complete_fps={estimate["complete_frame_estimate_fps"]:.2f} board_verified=0')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report(args.job,args.archive,args.output)
