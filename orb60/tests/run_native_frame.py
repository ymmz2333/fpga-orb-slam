"""Native bulk integration gate, with explicit DDR-model limits and frozen inputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from prepare_native_frame import prepare
from check_native_harness import check


def run(args):
    state = dict(State='RUNNING', Stage='PREPARE', ProcessId=args.parent_pid,
                 StartedUtc=datetime.now(timezone.utc).isoformat(),
                 Scope='Actual two-core RTL, one randomized arbitrated DDR model; host scheduling only, no PS firmware/AMD DDR PHY/board claim')
    state.update(LayerHlsJob=str(args.layer.resolve()),DescriptorHlsJob=str(args.descriptor.resolve()),
                 BenchmarkJob=str(args.benchmark.resolve()),ProtocolJob=str(args.protocol.resolve()))
    def save(): (args.output/'status.json').write_text(json.dumps(state, indent=2)+'\n')
    save()
    try:
        proof = json.loads((args.protocol/'status.json').read_text(encoding='utf-8-sig'))
        assert proof['State'] == 'SUCCEEDED'
        assert Path(proof['LayerHlsJob']).resolve() == args.layer.resolve()
        assert Path(proof['DescriptorHlsJob']).resolve() == args.descriptor.resolve()
        for entry in json.loads((args.output/'test_manifest.json').read_text(encoding='utf-8-sig')):
            assert hashlib.sha256((args.output/entry['Path']).read_bytes()).hexdigest().upper() == entry['SHA256']
        scratch = Path(os.environ['FPGA_VIVADO_BUILD_ROOT'])/'orb60'/('n'+args.output.name[-8:])
        scratch.mkdir(parents=True, exist_ok=False)
        state['Scratch'] = str(scratch);save()
        images = prepare(args, scratch)
        period_ps=round(json.loads((args.layer/'status.json').read_text(encoding='utf-8-sig'))['PeriodNs']*1000)
        frequency_mhz=1000000/period_ps
        check(scratch,Path(__file__).resolve().parent,args.output)
        shutil.copyfile(Path(__file__).with_name('native_frame.cpp'), scratch/'native_frame.cpp')
        shutil.copyfile(Path(__file__).with_name('ddr_time.hpp'), scratch/'ddr_time.hpp')
        rtl = sorted(scratch.glob('layer2/*.v')) + sorted(scratch.glob('descriptor/*.v'))
        version = subprocess.run([str(args.verilator), '--version'], capture_output=True, text=True, check=True)
        (args.output/'tool_version.txt').write_text(version.stdout+version.stderr)
        state['Stage']='COMPILE';save()
        # Windows .cmd launchers have an 8191-character command limit. Keep the
        # immutable RTL list in Verilator's native argument-file format.
        sources=['orb60_frame_top.sv','native_frame.cpp']+[p.relative_to(scratch).as_posix() for p in rtl]
        (scratch/'sources.f').write_text('\n'.join(sources)+'\n')
        if args.preflight:
            state['Stage']='LINT_PREFLIGHT';save()
            with (args.output/'lint.log').open('w') as log:
                code=subprocess.run([str(args.verilator),'--lint-only','--no-timing','-Wno-fatal',
                    '--top-module','orb60_frame_top','-I'+str(scratch/'layer2'),'-I'+str(scratch/'descriptor'),
                    '-f','sources.f'],cwd=scratch,stdout=log,stderr=subprocess.STDOUT).returncode
            if code: raise RuntimeError(f'RTL profile/wrapper lint exit {code}; inspect lint.log')
            state.update(State='SUCCEEDED',Stage='HARNESS_PREFLIGHT_ONLY',
                Scope='Actual RTL profile wrapper lint and C++ DDR pin-stub checks only; no RTL frame/route result')
            print('ORB60_NATIVE_PREFLIGHT_PASS',flush=True);return
        cmd = [str(args.verilator), '--cc', '--exe', '--build', '--no-timing', '-j', '4', '-Wno-fatal',
               '--top-module', 'orb60_frame_top', '--Mdir', 'obj', '-CFLAGS', '-std=c++17 -O2',
               '-I'+str(scratch/'layer2'), '-I'+str(scratch/'descriptor'),
               '-f','sources.f']
        print('ORB60_NATIVE_COMPILE', flush=True)
        with (args.output/'compile.log').open('w') as log:
            code=subprocess.run(cmd, cwd=scratch, stdout=log, stderr=subprocess.STDOUT).returncode
        if code: raise RuntimeError(f'Verilator compilation exit {code}; inspect compile.log')
        exe = scratch/'obj/Vorb60_frame_top.exe'
        assert exe.is_file(), exe
        with (args.output/'link_reset.log').open('w') as log:
            code=subprocess.run([str(exe),'--link-smoke'],cwd=scratch,stdout=log,stderr=subprocess.STDOUT).returncode
        if code: raise RuntimeError(f'Native link/reset startup exit {code}; inspect link_reset.log')
        runs = []
        for beats, stalls, seed, read_min, read_max in ((2,0,6001,0,5),(1,27,6002,0,5),
                                                      (2,0,6001,40,60),(1,27,6002,40,60)):
            label=f'beats{beats}_stall{stalls}'
            if read_min: label+=f'_read{read_min}_{read_max}'
            state['Stage']='SIMULATE_'+label;save()
            result=args.output/(label+'.json')
            print('ORB60_NATIVE_SIMULATE '+label, flush=True)
            command=[str(exe),str(images.resolve()),str((args.descriptor/'descriptor_vectors').resolve()),
                     str(result.resolve()),str(beats),str(stalls),str(seed),'--read-delay',str(read_min),str(read_max)]
            with (args.output/(label+'.log')).open('w') as log:
                code=subprocess.run(command, cwd=scratch, stdout=log, stderr=subprocess.STDOUT).returncode
            if code: raise RuntimeError(f'Native simulation {label} exit {code}; inspect {label}.log')
            value=json.loads(result.read_text())
            assert value['status']=='PASS' and len(value['frames'])==3
            assert value['read_initial_delay_cycles']==[read_min,read_max]
            assert value['ddr_beats_per_cycle']==beats and value['random_stall_percent']==stalls
            assert value['hp_shared_service_limit']==1 and value['hp_mapping']==[0,3,1,2,0,1,3,2]
            assert value['clock_period_ps']==period_ps and value['axi_metric_version']==2
            assert value['ddr_capacity_bytes_per_second']==beats*800000000
            assert value['hp_capacity_bytes_per_second']==800000000
            assert value['read_initial_delay_ns']==[read_min*10,read_max*10]
            assert value['write_response_delay_ns']==[20,310]
            assert [v['selected'] for v in value['frames']]==[280,942,0]
            for frame in value['frames']:
                frame['milliseconds']=frame['cycles']*period_ps/1000000000
                frame['equivalent_fps']=1e12/(frame['cycles']*period_ps)
                assert len(frame['axi_ports'])==8 and len(frame['layers'])==8
                axi=frame['axi_ports'];ddr=frame['ddr_service'];cycles=frame['cycles']
                assert sum(p['read_bytes'] for p in axi)==frame['read_bytes']
                assert sum(p['write_bytes'] for p in axi)==frame['write_bytes']
                assert sum(x['image_axi_bytes']+x['descriptor_axi_bytes'] for x in frame['layers'])==frame['read_bytes']+frame['write_bytes']
                assert ddr['used_cycles']+ddr['idle_cycles']==cycles
                assert ddr['read_beats']==sum(p['accepted_r'] for p in axi)
                assert ddr['write_beats']==sum(p['accepted_w'] for p in axi)
                transferred=ddr['read_beats']+ddr['write_beats']
                assert ddr['used_cycles']<=transferred<=ddr['used_cycles']*beats
                assert sum(ddr['hp_service_beats'])==transferred
                assert transferred<=cycles*period_ps*beats/10000+beats
                assert all(n<=cycles*period_ps/10000+1 for n in ddr['hp_service_beats'])
                ddr['service_slot_utilization']=transferred/(cycles*period_ps*beats/10000)
                for port in axi:
                    assert port['read_outstanding_max']<=8 and port['write_outstanding_max']<=8
                    assert port['accepted_aw']==port['accepted_b']
                    assert port['accepted_ar']<=port['accepted_r']
                    assert port['read_outstanding_cycle_sum']<=cycles*port['read_outstanding_max']
                    assert port['read_outstanding_cycle_sum']<=port['read_pending_cycles']*port['read_outstanding_max']
                    assert port['read_pending_cycles']<=port['read_outstanding_cycle_sum']
                    assert port['write_outstanding_cycle_sum']<=cycles*port['write_outstanding_max']
                    port['read_outstanding_mean']=port['read_outstanding_cycle_sum']/cycles
                    port['write_outstanding_mean']=port['write_outstanding_cycle_sum']/cycles
                profile=frame['profile'];fifos=frame['fifo_watermarks']
                meta=json.loads((args.output/'profile_manifest.json').read_text())
                assert len(profile)==len(meta['probes']) and len(fifos)==len(meta['fifos'])
                for spec,watermark in zip(meta['fifos'],fifos):
                    assert profile[spec['push']]['cycles']==profile[spec['pop']]['cycles']
                    assert 0<=watermark['max_occupancy']<=spec['depth']
            runs.append(value)
        # Prove neither native integration nor staging altered the accepted RTL.
        for entry in json.loads((args.output/'rtl_manifest.json').read_text()):
            job=args.layer if entry['kernel']=='layer2' else args.descriptor
            source=job/f"projects/{entry['kernel']}/solution1/syn/verilog/{entry['name']}"
            assert hashlib.sha256(source.read_bytes()).hexdigest()==entry['sha256']
        layer_config=json.loads((args.layer/'status.json').read_text(encoding='utf-8-sig'))
        descriptor_config=json.loads((args.descriptor/'status.json').read_text(encoding='utf-8-sig'))
        result=dict(status='PASS', frequency_mhz=frequency_mhz, clock_period_ps=period_ps, runs=runs, physical_board_fps_verified=False,
                    ps_modified=False, rtl_unchanged=True,
                    layer_ppc=layer_config.get('LayerPpc',2),fast_staged=layer_config.get('FastStaged',False),
                    descriptor_width_mode=descriptor_config.get('DescriptorWidthMode',0),
                    descriptor_prefetch=descriptor_config.get('DescriptorPrefetch',0),
                    descriptor_patch32=descriptor_config.get('DescriptorPatch32',False),
                    descriptor_moment_fusion=descriptor_config.get('DescriptorMomentFusion',0),
                    descriptor_fast_quantize=descriptor_config.get('DescriptorFastQuantize',0),
                    slice_compact_mode=layer_config.get('SliceCompactMode',0),
                    limits=['DDR service budgets are hypotheses, not measured Zynq DDR/AMD-interconnect models',
                            'Strict descriptor(n)/image(n+1) overlap includes simulated AXI-Lite scheduling',
                            'Three inputs and four service configurations do not establish representative-video P99/max',
                            'Port wait counters overlap each other; actor busy includes waiting and is not pure computation',
                            'Initial read delay is eligibility after accepted AR; actual first R may wait longer for service/backpressure',
                            'Board PS cache visibility/DDR bandwidth/video/power remain unverified'])
        (args.output/'performance.json').write_text(json.dumps(result,indent=2)+'\n')
        state.update(State='SUCCEEDED', Stage='COMPLETE')
        print('ORB60_NATIVE_FRAME_PASS',flush=True)
    except BaseException as error:
        state.update(State='FAILED', Error=str(error));raise
    finally:
        state['FinishedUtc']=datetime.now(timezone.utc).isoformat();save()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('layer','descriptor','benchmark','protocol','verilator','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--parent-pid',type=int,required=True)
    p.add_argument('--preflight',action='store_true')
    run(p.parse_args())
