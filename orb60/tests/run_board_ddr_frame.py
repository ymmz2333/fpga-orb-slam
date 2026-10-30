"""Re-evaluate accepted RTL with ACZ7015 capacity budgets; never a board claim."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace

from prepare_native_frame import prepare
from check_native_harness import check


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def board_config(path, effective_mbps):
    text = path.read_text(encoding='utf-8-sig')
    def setting(name):
        match = re.search(r'CONFIG\.' + re.escape(name) + r'\s+(\{[^}]*\}|\S+)', text)
        if not match:
            raise ValueError('Missing PS DDR setting: ' + name)
        return match.group(1).strip('{}')
    width = int(setting('PCW_UIPARAM_DDR_BUS_WIDTH').split()[0])
    mhz = Decimal(setting('PCW_UIPARAM_DDR_FREQ_MHZ'))
    if width not in (16, 32) or not 0 < mhz <= 1000:
        raise ValueError('Unsupported PS DDR width or frequency')
    physical = int(mhz * 1000000 * 2 * width / 8)
    capacity = physical if effective_mbps == 0 else int(effective_mbps * 1000000)
    if not 0 < capacity <= physical:
        raise ValueError('Effective DDR budget must be positive and no greater than the physical peak')
    return dict(board='ACZ7015', ddr_bus_bits=width, ddr_clock_mhz=str(mhz),
                physical_peak_bytes_per_second=physical, capacity_bytes_per_second=capacity,
                capacity_basis='ps_config_physical_peak' if effective_mbps == 0 else 'user_capacity_budget',
                effective_bandwidth_measured=False, ps_config_sha256=sha(path),
                hp_bus_bits=64, hp_ddri_port_mapping=[3, 3, 2, 2],
                hp_ddri_pair_cycle_timing_modeled=False, ddr_bank_refresh_timing_modeled=False,
                sources=['https://fpga.cn/forum.php?mod=viewthread&tid=29414',
                         'https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Interconnect'])


def validate(value, period, rate, board, meta):
    assert value['status'] == 'PASS' and len(value['frames']) == 3
    assert value['clock_period_ps'] == period and value['axi_metric_version'] == 2
    assert value['ddr_capacity_bytes_per_second'] == rate
    assert value['hp_capacity_bytes_per_second'] == (8000000000000 // period if board else 800000000)
    assert value['hp_independent_read_write'] == board
    assert value['hp_shared_service_limit'] == (0 if board else 1)
    assert value['ddr_model'] == ('board_spec_capacity' if board else 'legacy_reference')
    assert value['hp_mapping'] == [0, 3, 1, 2, 0, 1, 3, 2]
    assert [f['selected'] for f in value['frames']] == [280, 942, 0]
    assert value['write_response_delay_ns'] == [20, 310]
    for f in value['frames']:
        cycles = f['cycles']; axi = f['axi_ports']; service = f['ddr_service']
        assert cycles > 0 and len(axi) == 8 and len(f['layers']) == 8
        assert sum(p['read_bytes'] for p in axi) == f['read_bytes']
        assert sum(p['write_bytes'] for p in axi) == f['write_bytes']
        assert sum(l['image_axi_bytes'] + l['descriptor_axi_bytes'] for l in f['layers']) == f['read_bytes'] + f['write_bytes']
        assert service['used_cycles'] + service['idle_cycles'] == cycles
        assert service['read_beats'] == sum(p['accepted_r'] for p in axi)
        assert service['write_beats'] == sum(p['accepted_w'] for p in axi)
        transferred = service['read_beats'] + service['write_beats']
        assert sum(service['hp_service_beats']) == transferred
        assert sum(service['hp_read_service_beats']) == service['read_beats']
        assert sum(service['hp_write_service_beats']) == service['write_beats']
        assert service['used_cycles'] <= transferred <= service['used_cycles'] * value['ddr_beats_per_cycle']
        # Fractional service credit at a frame boundary is less than one beat.
        assert transferred * 8000000000000 <= cycles * period * rate + 8000000000000
        for hp in range(4):
            reads = sum(p['accepted_r'] for p in axi if p['hp'] == hp)
            writes = sum(p['accepted_w'] for p in axi if p['hp'] == hp)
            assert reads == service['hp_read_service_beats'][hp]
            assert writes == service['hp_write_service_beats'][hp]
            if board:
                assert reads <= cycles and writes <= cycles
            else:
                assert reads + writes <= cycles * period // 10000 + 1
        for p in axi:
            assert p['accepted_aw'] == p['accepted_b'] and p['accepted_ar'] <= p['accepted_r']
            assert p['read_outstanding_max'] <= 8 and p['write_outstanding_max'] <= 8
            assert p['read_outstanding_cycle_sum'] <= cycles * p['read_outstanding_max']
            assert p['read_pending_cycles'] <= p['read_outstanding_cycle_sum']
            assert p['read_outstanding_cycle_sum'] <= p['read_pending_cycles'] * p['read_outstanding_max']
            assert p['write_outstanding_cycle_sum'] <= cycles * p['write_outstanding_max']
        assert len(f['profile']) == len(meta['probes']) and len(f['fifo_watermarks']) == len(meta['fifos'])
        for spec, water in zip(meta['fifos'], f['fifo_watermarks']):
            assert f['profile'][spec['push']]['cycles'] == f['profile'][spec['pop']]['cycles']
            assert 0 <= water['max_occupancy'] <= spec['depth']
        f['milliseconds'] = cycles * period / 1e9
        f['equivalent_fps'] = 1e12 / (cycles * period)
        service['capacity_utilization'] = transferred * 8 / (cycles * period * rate / 1e12)


def run(args):
    state = dict(State='RUNNING', Stage='PREPARE', ProcessId=args.parent_pid,
                 StartedUtc=datetime.now(timezone.utc).isoformat(), SourceFrameJob=str(args.frame_job.resolve()),
                 Scope='Simulation-capacity change only; accepted HLS RTL and FPGA/PS source unchanged')
    def save():
        (args.output / 'status.json').write_text(json.dumps(state, indent=2) + '\n')
    save()
    try:
        source = json.loads((args.frame_job / 'status.json').read_text(encoding='utf-8-sig'))
        assert source['State'] == 'SUCCEEDED' and source['Stage'] == 'COMPLETE'
        paths = SimpleNamespace(layer=Path(source['LayerHlsJob']), descriptor=Path(source['DescriptorHlsJob']),
                                benchmark=Path(source['BenchmarkJob']), protocol=Path(source['ProtocolJob']), output=args.output)
        proof = json.loads((paths.protocol / 'status.json').read_text(encoding='utf-8-sig'))
        assert proof['State'] == 'SUCCEEDED'
        assert Path(proof['LayerHlsJob']).resolve() == paths.layer.resolve()
        assert Path(proof['DescriptorHlsJob']).resolve() == paths.descriptor.resolve()
        for entry in json.loads((args.output / 'test_manifest.json').read_text(encoding='utf-8-sig')):
            assert sha(args.output / entry['Path']).upper() == entry['SHA256']
        config = board_config(args.output / 'inputs/ps_config.tcl', args.effective_ddr_mbps)
        (args.output / 'board_ddr_config.json').write_text(json.dumps(config, indent=2) + '\n')
        source_period = json.loads((paths.layer / 'status.json').read_text(encoding='utf-8-sig'))['PeriodNs'] * 1000
        period = round(source_period)
        assert 5000 <= period <= 10000 and abs(period-source_period) <= .5
        old_scratch = Path(source['Scratch'])
        scratch = Path(os.environ['FPGA_VIVADO_BUILD_ROOT']) / 'orb60' / ('b' + args.output.name[-8:])
        scratch.mkdir(parents=True, exist_ok=False)
        state.update(Scratch=str(scratch), ClockPeriodPs=period, BoardDdrConfig=config); save()
        images = prepare(paths, scratch)
        # Cache reuse is allowed only for byte-identical generated RTL, wrapper,
        # and register/profile headers, from the already completed frame job.
        cache_proof = []
        for path in [scratch / 'orb60_frame_top.sv', scratch / 'frame_registers.hpp'] + sorted(scratch.glob('layer2/*.v')) + sorted(scratch.glob('descriptor/*.v')):
            relative = path.relative_to(scratch)
            assert sha(path) == sha(old_scratch / relative), str(relative)
            cache_proof.append(dict(path=relative.as_posix(), sha256=sha(path)))
        (args.output / 'rtl_cache_pair.json').write_text(json.dumps(cache_proof, indent=2) + '\n')
        state['Stage'] = 'MODEL_CHECK'; save()
        tests = Path(__file__).resolve().parent
        check(scratch, tests, args.output)
        for name in ('native_frame.cpp', 'ddr_time.hpp'):
            shutil.copyfile(tests / name, scratch / name)
        state['Stage'] = 'RELINK_ACCEPTED_VERILATOR_MODEL'; save()
        shutil.copytree(old_scratch / 'obj', scratch / 'obj')
        # C++ HDL archive is not regenerated or edited. Only the new harness is
        # recompiled; GNU make may rebuild other dependencies if needed.
        compiler = shutil.which('g++'); make = shutil.which('make') or shutil.which('mingw32-make')
        assert compiler and make
        (args.output / 'compiler_version.txt').write_text(subprocess.check_output([compiler, '--version'], text=True))
        with (args.output / 'compile.log').open('w') as log:
            subprocess.run([make, '-f', 'Vorb60_frame_top.mk', '-j', '2', 'CXX=' + compiler.replace('\\', '/')],
                           cwd=scratch / 'obj', stdout=log, stderr=subprocess.STDOUT, check=True)
        exe = scratch / 'obj/Vorb60_frame_top.exe'
        assert exe.exists()
        with (args.output / 'link_reset.log').open('w') as log:
            subprocess.run([str(exe), '--link-smoke'], cwd=scratch, stdout=log, stderr=subprocess.STDOUT, check=True)
        meta = json.loads((args.output / 'profile_manifest.json').read_text())
        legacy = json.loads((args.frame_job / 'performance.json').read_text())
        reference = next(r for r in legacy['runs'] if r['ddr_beats_per_cycle'] == 1 and r['random_stall_percent'] == 27 and r['read_initial_delay_cycles'] == [40, 60])
        configurations = [('legacy_replay', 1, 27, 6002, 40, 60, False)]
        configurations += [(f'board_stall{stall}_read{lo}_{hi}', 4, stall, seed, lo, hi, True)
                           for stall, seed, lo, hi in ((0, 6001, 0, 5), (0, 6001, 40, 60), (27, 6002, 0, 5), (27, 6002, 40, 60))]
        runs = []
        for label, beats, stalls, seed, lo, hi, board in configurations:
            state['Stage'] = 'SIMULATE_' + label; save()
            print('ORB60_BOARD_DDR_SIMULATE ' + label, flush=True)
            result = args.output / (label + '.json')
            command = [str(exe), str(images.resolve()), str((paths.descriptor / 'descriptor_vectors').resolve()),
                       str(result.resolve()), str(beats), str(stalls), str(seed), '--read-delay', str(lo), str(hi)]
            rate = config['capacity_bytes_per_second'] if board else 800000000
            if board:
                command += ['--board-ddr-bytes-per-second', str(rate)]
            with (args.output / (label + '.log')).open('w') as log:
                subprocess.run(command, cwd=scratch, stdout=log, stderr=subprocess.STDOUT, check=True)
            value = json.loads(result.read_text())
            validate(value, period, rate, board, meta)
            assert value['random_stall_percent'] == stalls and value['seed'] == seed
            assert value['read_initial_delay_cycles'] == [lo, hi] and value['read_initial_delay_ns'] == [lo * 10, hi * 10]
            if not board:
                for actual, old in zip(value['frames'], reference['frames']):
                    for key in ('frame', 'selected', 'cycles', 'overlap_cycles', 'read_bytes', 'write_bytes',
                                'arbitration_or_random_wait_cycles', 'layers', 'axi_ports', 'profile', 'fifo_watermarks'):
                        # Performance summaries add means; compare raw pin counters.
                        if key == 'axi_ports':
                            for a, b in zip(actual[key], old[key]):
                                assert all(a[k] == v for k, v in b.items() if k in a), (label, key)
                        else:
                            assert actual[key] == old[key], (label, key)
                state['LegacyReplayExact'] = True; save()
            else:
                runs.append(value)
            for f in value['frames']:
                print(f"BOARD_DDR_FRAME {label} points={f['selected']} ms={f['milliseconds']:.5f} fps={f['equivalent_fps']:.2f}", flush=True)
        for entry in json.loads((args.output / 'rtl_manifest.json').read_text()):
            job = paths.layer if entry['kernel'] == 'layer2' else paths.descriptor
            assert sha(job / f"projects/{entry['kernel']}/solution1/syn/verilog/{entry['name']}") == entry['sha256']
        result = dict(status='PASS', frequency_mhz=1000000 / period, board_ddr_config=config, runs=runs,
                      legacy_replay_exact=True, rtl_unchanged=True, ps_modified=False, physical_board_fps_verified=False,
                      limits=['Physical DDR peak is not a measured effective bandwidth.',
                              'HP read/write directions are independent; masters sharing each direction arbitrate.',
                              'DDRI pairing is recorded; its internal clock/queue arbitration is not cycle-accurate.',
                              'Bank/row/refresh/turnaround and PS/CPU contention are not modeled.',
                              '0/27% stalls and 0-50/400-600ns eligibility delays are experimental conditions, not board calibration.',
                              'These 12 frames do not establish representative-video P99 or board FPS.'])
        (args.output / 'performance.json').write_text(json.dumps(result, indent=2) + '\n')
        state.update(State='SUCCEEDED', Stage='COMPLETE'); print('ORB60_BOARD_DDR_PASS', flush=True)
    except BaseException as error:
        state.update(State='FAILED', Error=str(error)); raise
    finally:
        state['FinishedUtc'] = datetime.now(timezone.utc).isoformat(); save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--frame-job', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--effective-ddr-mbps', type=Decimal, default=Decimal(0))
    run(parser.parse_args())
