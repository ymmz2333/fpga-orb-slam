"""Check the generated 2018.3 PL's software-facing contract, without Vivado."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as E


def inspect(root):
    bdroot = root / 'vivado/p.srcs/sources_1/bd/s'
    bd = json.loads((bdroot / 's.bd').read_text())['design']
    state = json.loads((root / 'status.json').read_text())
    checks = []

    def check(name, actual, expected):
        passed = (math.isclose(float(actual), expected, rel_tol=1e-6)
                  if isinstance(expected, (float, int)) else actual == expected)
        checks.append(dict(name=name, actual=actual, expected=expected, passed=passed))

    def parameters(cell):
        x = E.parse(bdroot / 'ip' / cell / (cell + '.xci'))
        return {e.attrib.get('{http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009}referenceId'): e.text
                for e in x.iter() if e.tag.endswith('}configurableElementValue')}

    ps = parameters('s_ps7_0')
    reset = parameters('s_reset_0')
    clock = parameters('s_clockgen_0')
    for key, expected in [('PCW_FPGA0_PERIPHERAL_FREQMHZ',100), ('PCW_UIPARAM_DDR_FREQ_MHZ',533.333333),
                          *[('PCW_USE_S_AXI_HP' + str(i),1) for i in range(4)]]:
        check('ps7.' + key, ps.get('PARAM_VALUE.' + key, 'nan'), expected)
    check('reset.polarity', reset.get('BUSIFPARAM_VALUE.EXT_RESET.POLARITY'), 'ACTIVE_LOW')
    check('reset.derived_value', reset.get('MODELPARAM_VALUE.C_EXT_RESET_HIGH', 'nan'), 0)
    for key, expected in [('PRIM_IN_FREQ',100), ('CLKOUT1_REQUESTED_OUT_FREQ',150),
                          ('MMCM_DIVCLK_DIVIDE',2), ('MMCM_CLKFBOUT_MULT_F',19.875), ('MMCM_CLKOUT0_DIVIDE_F',6.625)]:
        check('clockgen.' + key, clock.get('PARAM_VALUE.' + key, 'nan'), expected)
    for cell in ('layer_control_slice', 'desc_control_slice'):
        for key in ('REG_AW','REG_W','REG_B','REG_AR','REG_R'):
            check(cell + '.' + key, bd['components'][cell]['parameters'][key]['value'], '7')
    segments = bd['addressing']['/ps7']['address_spaces']['Data']['segments']
    for core, offset in [('layer', '0x43C00000'), ('desc', '0x43C10000')]:
        segment = segments['SEG_' + core + '_Reg']
        check(core + '.control_address', segment['offset'].upper(), offset.upper())
        check(core + '.control_range', segment['range'], '32K' if state.get('video2') and core=='layer' else '64K')
    if state.get('video2'):
        segment=segments['SEG_video_reg0']
        check('video.control_address',segment['offset'].upper(),'0X43C08000')
        check('video.control_range',segment['range'],'32K')
        check('mem3.NUM_SI',bd['components']['mem3']['parameters']['NUM_SI']['value'],'3')
        check('mem3.S02_HAS_REGSLICE',bd['components']['mem3']['parameters']['S02_HAS_REGSLICE']['value'],'1')
        vclk=parameters('s_video_clock_0')
        for key,expected in [('CLKOUT1_REQUESTED_OUT_FREQ',371.25),('CLKOUT2_REQUESTED_OUT_FREQ',74.25),
                             ('MMCM_DIVCLK_DIVIDE',5),('MMCM_CLKFBOUT_MULT_F',37.125),
                             ('MMCM_CLKOUT0_DIVIDE_F',2),('MMCM_CLKOUT1_DIVIDE',10)]:
            check('video_clock.'+key,vclk.get('PARAM_VALUE.'+key,'nan'),expected)
        for name,expected in state['video_inputs_sha256'].items():
            check('video.source.'+name,hashlib.sha256((root/'video'/name).read_bytes()).hexdigest(),expected)
    if state.get('mem2_slices'):
        for port in ('S00', 'S01'):
            check('mem2.' + port + '_HAS_REGSLICE',
                  bd['components']['mem2']['parameters'][port + '_HAS_REGSLICE']['value'], '1')
    # Validate complete exported IP contents, including .dat ROM initialization.
    for record in json.loads((root / 'staged_ip_hashes.json').read_text()):
        actual = hashlib.sha256((root / record['path']).read_bytes()).hexdigest()
        if actual != record['sha256']:
            checks.append(dict(name=record['path'], passed=False, actual=actual, expected=record['sha256']))
    result = {'status': 'PASS' if all(c['passed'] for c in checks) else 'FAIL',
              'scope': 'generated configuration and immutable HLS export; not simulation/timing/board acceptance',
              'checks': checks, 'ip_files_checked': len(json.loads((root / 'staged_ip_hashes.json').read_text()))}
    (root / 'contract_check.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'], len(checks), 'configuration checks;', result['ip_files_checked'], 'IP file hashes')
    for check in checks:
        if not check['passed']:
            print(check)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    sys.exit(inspect(parser.parse_args().run.resolve()))
