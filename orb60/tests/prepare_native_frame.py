"""Generate an authored two-core wrapper; preserve all generated HLS RTL bytes."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
from native_profile import bind_profile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_vectors(path):
    info = json.loads((path / 'vectors.json').read_text())
    for name, digest in info['sha256'].items():
        assert sha(path / name) == digest, name
    return info


def offsets(job, kernel):
    top = f'fastv2_{kernel}_hls'
    header = job / f'projects/{kernel}/solution1/impl/ip/drivers/{top}_v1_0/src/x{top}_hw.h'
    source = header.read_text()
    entries = dict((k.removesuffix('_DATA'), int(v, 16)) for k, v in re.findall(
        r'#define\s+XFASTV2_\w+_HLS_CONTROL_ADDR_(\w+)\s+(0x[0-9a-fA-F]+)', source))
    for key in ('STATS', 'BLURRED'):
        assert re.search(rf'_CONTROL_BITS_{key}_DATA\s+32\b', source)
    return entries


def prepare(args, scratch):
    bench = json.loads((args.benchmark / 'status.json').read_text(encoding='utf-8-sig'))
    assert bench['State'] == 'SUCCEEDED'
    images = args.benchmark / 'vectors'
    image_info = checked_vectors(images)
    controls = (images / 'cases.bin').read_bytes()
    assert struct.unpack_from('<4I',controls) == (0x60B20001,1,3,24)
    budgets = (217,181,151,126,105,87,73,60)
    for case in range(24):
        frame,level,width,height,budget,high,low,dual = struct.unpack_from('<8I',controls,16+case*32)
        assert (frame,level,budget,high,low,dual) == (case//8,case%8,budgets[case%8],20,7,1)
    desc_info = checked_vectors(args.descriptor / 'descriptor_vectors')
    assert Path(desc_info['source_vectors']).resolve() == images.resolve()
    declarations = ['input wire clk', 'input wire rst_n', 'output wire done [0:1]',
                    'output wire profile_bits [0:511]']
    memory = {
        'AWVALID': ('output', 1), 'AWREADY': ('input', 1), 'AWADDR': ('output', 32),
        'AWID': ('output', 1), 'AWLEN': ('output', 8), 'AWSIZE': ('output', 3), 'AWBURST': ('output', 2),
        'WVALID': ('output', 1), 'WREADY': ('input', 1), 'WDATA': ('output', 64),
        'WSTRB': ('output', 8), 'WLAST': ('output', 1),
        'ARVALID': ('output', 1), 'ARREADY': ('input', 1), 'ARADDR': ('output', 32),
        'ARID': ('output', 1), 'ARLEN': ('output', 8), 'ARSIZE': ('output', 3), 'ARBURST': ('output', 2),
        'RVALID': ('input', 1), 'RREADY': ('output', 1), 'RDATA': ('input', 64),
        'RLAST': ('input', 1), 'RID': ('input', 1), 'RRESP': ('input', 2),
        'BVALID': ('input', 1), 'BREADY': ('output', 1), 'BRESP': ('input', 2), 'BID': ('input', 1),
    }
    control = {
        'AWVALID': ('input', 1), 'AWREADY': ('output', 1), 'AWADDR': ('input', 7),
        'WVALID': ('input', 1), 'WREADY': ('output', 1), 'WDATA': ('input', 32), 'WSTRB': ('input', 4),
        'ARVALID': ('input', 1), 'ARREADY': ('output', 1), 'ARADDR': ('input', 7),
        'RVALID': ('output', 1), 'RREADY': ('input', 1), 'RDATA': ('output', 32), 'RRESP': ('output', 2),
        'BVALID': ('output', 1), 'BREADY': ('input', 1), 'BRESP': ('output', 2),
    }
    for prefix, fields, last in (('m', memory, 7), ('c', control, 1)):
        for name, (direction, width) in fields.items():
            declarations.append(f'{direction} wire [{width-1}:0] {prefix}_{name} [0:{last}]')
    wrapper = 'module orb60_frame_top (\n' + ',\n'.join(declarations) + '\n);\n'
    manifest = []
    zero_delay_count = 0
    header = '#pragma once\n'
    period_ps=None
    module_definitions = {}
    for index, kernel in enumerate(('layer2', 'descriptor')):
        job = getattr(args, 'layer' if index == 0 else 'descriptor')
        state = json.loads((job / 'status.json').read_text(encoding='utf-8-sig'))
        assert state['State'] == 'SUCCEEDED' and state['Cosim'] and state['Kernel'] == kernel
        current_period=round(state['PeriodNs']*1000)
        assert 5000<=current_period<=10000 and abs(current_period-state['PeriodNs']*1000)<=0.5 and state['Part']=='xc7z015clg485-2', 'Native harness clock/part mismatch'
        if period_ps is None:
            period_ps=current_period
            header+=f'constexpr unsigned CLOCK_PERIOD_PS={period_ps};\n'
        else:assert period_ps==current_period,'Both IPs must be regenerated at the same clock'
        if index==0:
            ppc=state.get('LayerPpc',2);assert ppc in (2,4)
            header+=f'constexpr unsigned LAYER_PPC={ppc},LAYER_VERSION=0x{(0x600003 if ppc==4 else 0x600001):x};\n'
        for entry in json.loads((job / 'source_manifest.json').read_text(encoding='utf-8-sig')):
            assert sha(job / 'inputs' / entry['Path']).upper() == entry['SHA256']
        rtl = job / f'projects/{kernel}/solution1/syn/verilog'
        destination = scratch / kernel
        destination.mkdir()
        for source in sorted(rtl.iterdir()):
            if source.suffix not in ('.v', '.sv', '.dat'):
                continue
            # Colliding module definitions must be byte-identical. Never rename generated HDL.
            if source.suffix in ('.v', '.sv'):
                source_text = source.read_text()
                # This C++ clocked harness has no event-time scheduler. Vendor
                # RTL uses #0 only for initialization; never ignore real delays.
                delays = re.findall(r'#\s*(\d+(?:\.\d+)?)\b', source_text)
                assert all(float(delay) == 0 for delay in delays), f'Nonzero RTL delay: {source.name}'
                # Parameter override #(...) is allowed, procedural #(delay) is not.
                for delay in re.findall(r'#\s*\(([^\n]*?)\)', source_text):
                    assert delay.lstrip().startswith('.'), f'Expression delay/positional override: {source.name}'
                zero_delay_count += len(delays)
                for name in re.findall(r'^module\s+(\w+)', source_text, re.M):
                    if name in module_definitions:
                        assert module_definitions[name] == sha(source), name
                    else:
                        module_definitions[name] = sha(source)
            shutil.copyfile(source, destination / source.name)
            if source.suffix == '.dat':
                target = scratch / source.name
                if target.exists(): assert sha(target) == sha(source), source.name
                else: shutil.copyfile(source, target)
            manifest.append(dict(kernel=kernel, name=source.name, sha256=sha(source)))
        top = f'fastv2_{kernel}_hls'
        source = (rtl / f'{top}.v').read_text()
        assert re.search(r'C_S_AXI_CONTROL_ADDR_WIDTH\s*=\s*7;', source)
        for port in range(4):
            assert re.search(rf'C_M_AXI_GMEM{port}_DATA_WIDTH\s*=\s*64;', source)
            assert re.search(rf'C_M_AXI_GMEM{port}_ADDR_WIDTH\s*=\s*32;', source)
        names = re.search(r'module\s+' + top + r'\s*\((.*?)\);', source, re.S).group(1)
        connections = []
        for name in re.findall(r'\b\w+\b', names):
            if name == 'ap_clk': value = 'clk'
            elif name == 'ap_rst_n': value = 'rst_n'
            elif name == 'interrupt': value = ''
            elif name.startswith('s_axi_control_'): value = f'c_{name[14:]}[{index}]'
            else:
                match = re.fullmatch(r'm_axi_gmem([0-3])_(\w+)', name)
                assert match, name
                port, signal = match.groups()
                if signal in memory: value = f'm_{signal}[{index*4+int(port)}]'
                elif signal in ('RUSER', 'BUSER'): value = "1'b0"
                else: value = ''
            connections.append(f'.{name}({value})')
        wrapper += f'{top} core{index} (\n' + ',\n'.join(connections) + '\n);\n'
        wrapper += f'assign done[{index}]=core{index}.ap_done;\n'
        header += f'namespace reg{index} {{\n'
        for name, value in offsets(job, kernel).items():
            header += f'constexpr unsigned {name}={value};\n'
        header += '}\n'
    profile_rtl, profile_header, profile_manifest = bind_profile([
        (getattr(args, field)/f'projects/{kernel}/solution1/syn/verilog', f'fastv2_{kernel}_hls')
        for field,kernel in (('layer','layer2'),('descriptor','descriptor'))])
    wrapper += profile_rtl+'endmodule\n'
    header += profile_header
    (args.output/'profile_manifest.json').write_text(json.dumps(profile_manifest,indent=2)+'\n')
    (scratch / 'orb60_frame_top.sv').write_text(wrapper)
    selected = [case['selected'] for case in image_info['cases']]
    reads = [(case['raw_read_bytes'], case['blur_read_bytes']) for case in desc_info['cases'][:24]]
    header += 'constexpr unsigned EXPECT_COUNT[24]={' + ','.join(map(str, selected)) + '};\n'
    header += 'constexpr unsigned EXPECT_PATCH_BYTES[24][2]={' + ','.join('{%d,%d}' % pair for pair in reads) + '};\n'
    (scratch / 'frame_registers.hpp').write_text(header)
    (args.output / 'rtl_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (args.output / 'delay_audit.json').write_text(json.dumps(dict(zero_delay_count=zero_delay_count,
        policy='--no-timing allowed only for vendor zero-delay initialization; explicit reset before transactions'), indent=2)+'\n')
    return images
