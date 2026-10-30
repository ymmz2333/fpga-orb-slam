"""Reuse cocotb/ModelSim and the shared AXI-Lite driver for isolated R11 IPs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

from cocotb_tools.runner import get_results, get_runner
from gpi_runtime import configure as configure_runtime

ROOT = Path(os.environ.get('FPGA_PROJECT_ROOT',Path(__file__).resolve().parents[2]))
HERE = Path(__file__).resolve().parent


def top_name(job, kernel):
    rtl = job / f'projects/{kernel}/solution1/syn/verilog'
    top = 'fastv2_front64_hls' if kernel == 'front' and (rtl / 'fastv2_front64_hls.v').is_file() else f'fastv2_{kernel}_hls'
    assert (rtl / f'{top}.v').is_file(), f'Missing RTL top {top}'
    return top


def control_offsets(job, kernel, top):
    header = job / f'projects/{kernel}/solution1/impl/ip/drivers/{top}_v1_0/src/x{top}_hw.h'
    text = header.read_text()
    definitions = {name: int(value, 16) for name, value in re.findall(
        r'#define\s+XFASTV2_\w+_HLS_CONTROL_ADDR_(\w+)\s+(0x[0-9A-Fa-f]+)', text)}
    offsets = {name.removesuffix('_DATA'): value for name, value in definitions.items()}
    pointers = {'front':('IMAGE_R','SELECTED','RESULT'),'front2':('IMAGE_R','SELECTED','RESULT'),
                'layer2':('IMAGE_R','BLURRED','RESIZED','SELECTED','RESULT','STATS'),
                'descriptor':('RAW','BLURRED','POINTS','FEATURES','STATS')}.get(kernel,('SOURCE','DESTINATION'))
    for pointer in pointers:
        assert re.search(rf'_CONTROL_BITS_{pointer}_DATA\s+32\b', text), f'{pointer} is not 32-bit'
    return offsets


def run(args):
    job = args.hls_job.resolve()
    state = json.loads((job / 'status.json').read_text(encoding='utf-8-sig'))
    kernels = ('front2',) if args.kernel == 'front2' else ('front', 'resize', 'gaussian')
    assert state['State'] == 'SUCCEEDED' and state['Cosim'] and state['Kernel'] == args.kernel
    for record in json.loads((job / 'source_manifest.json').read_text(encoding='utf-8-sig')):
        source = job / 'inputs' / record['Path']
        assert hashlib.sha256(source.read_bytes()).hexdigest().upper() == record['SHA256']
    modelsim = Path(os.environ['FPGA_MODELSIM_BIN'])
    license_file = Path(os.environ['FPGA_MODELSIM_LICENSE'])
    assert (modelsim / 'vsim.exe').is_file() and license_file.is_file()
    os.environ['MGLS_LICENSE_FILE'] = str(license_file)
    os.environ['PATH'] = str(modelsim) + os.pathsep + os.environ['PATH']
    # LM_LICENSE_FILE may belong to other applications; never overwrite it.
    sys.path[:0] = [str(HERE), str(ROOT / 'tb')]
    os.environ['PYTHONPATH'] = os.pathsep.join((str(HERE), str(ROOT / 'tb'), os.environ.get('PYTHONPATH', '')))
    args.output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    gate = {'state': 'RUNNING', 'hls_job': str(job), 'started_utc': started,
            'mode': 'smoke' if args.smoke else 'full', 'kernels': {}}
    status = args.output / 'status.json'
    status.write_text(json.dumps(gate, indent=2))
    try:
        for kernel in kernels:
            top = top_name(job, kernel)
            # Stage byte-identical generated HDL under the existing short scratch
            # root to avoid ModelSim's legacy Windows filename limit.
            scratch = Path(os.environ['FPGA_VIVADO_BUILD_ROOT']) / 'orb60' / args.output.parent.name / args.output.name / kernel
            scratch.mkdir(parents=True, exist_ok=False)
            rtl = job / f'projects/{kernel}/solution1/syn/verilog'
            for p in rtl.iterdir():
                if p.suffix in ('.v', '.sv', '.dat'):
                    shutil.copyfile(p, scratch / p.name)
            result = args.output / f'{kernel}.json'
            config = args.output / f'{kernel}_config.json'
            config.write_text(json.dumps(dict(kernel=kernel, vectors=str(args.vectors.resolve()),
                offsets=control_offsets(job, kernel, top), result=str(result.resolve())), indent=2))
            os.environ['ORB60_AXI_CONFIG'] = str(config.resolve())
            os.environ['ORB60_AXI_SMOKE'] = '1' if args.smoke else '0'
            gate['kernels'][kernel] = {'state': 'RUNNING', 'scratch': str(scratch)}
            configure_runtime(args.output / f'{kernel}_runtime')
            status.write_text(json.dumps(gate, indent=2))
            print(f'ORB60_AXI_BEGIN kernel={kernel} mode={gate["mode"]}', flush=True)
            runner = get_runner('questa')
            runner.build(hdl_toplevel=top,
                         sources=sorted(scratch.glob('*.v')) + sorted(scratch.glob('*.sv')),
                         build_dir=scratch, always=True)
            test_result = runner.test(hdl_toplevel=top,
                                      test_module='test_r11_axi', build_dir=scratch)
            total, failed = get_results(test_result)
            expected_cases = 2 if args.smoke else {'front': 11, 'front2': 16, 'resize': 13, 'gaussian': 14}[kernel]
            proof = json.loads(result.read_text()) if result.is_file() else {}
            assert total > 0 and failed == 0 and proof.get('status') == 'PASS'
            assert proof['transactions'] == expected_cases and proof['reset_interruption']
            gate['kernels'][kernel]['state'] = 'PASS'
            gate['kernels'][kernel]['result'] = str(result)
            status.write_text(json.dumps(gate, indent=2))
            print(f'ORB60_AXI_PASS kernel={kernel} transactions={expected_cases}', flush=True)
        gate['state'] = 'SUCCEEDED'
    except BaseException as error:
        gate['state'] = 'FAILED'
        gate['error'] = str(error)
        raise
    finally:
        gate['finished_utc'] = datetime.now(timezone.utc).isoformat()
        status.write_text(json.dumps(gate, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hls-job', type=Path, required=True)
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--kernel', choices=('all', 'front2'), default='all')
    run(parser.parse_args())
