"""Frequency/DDR capacity pin-model check; does not simulate HLS RTL."""
import argparse
import json
from pathlib import Path
import re
import shutil
from check_native_harness import check

def main():
    p=argparse.ArgumentParser();p.add_argument('--scratch',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    for period in (10000,8000,7000,6667,6000,5000):
        target=a.output/str(period);target.mkdir()
        shutil.copyfile(a.scratch/'orb60_frame_top.sv',target/'orb60_frame_top.sv')
        header=(a.scratch/'frame_registers.hpp').read_text()
        header,n=re.subn(r'CLOCK_PERIOD_PS=\d+;',f'CLOCK_PERIOD_PS={period};',header)
        assert n==1
        (target/'frame_registers.hpp').write_text(header)
        check(target,Path(__file__).resolve().parent,target)
        assert 'NATIVE_DDR_MODEL_PASS LEGACY_AND_BOARD_SPEC' in (target/'model_check.log').read_text()
        print(f'FREQUENCY_PIN_MODEL_PASS period_ps={period}',flush=True)
    (a.output/'result.json').write_text(json.dumps(dict(status='PASS',periods_ps=[10000,8000,7000,6667,6000,5000],
        scope='Pin stubs and shared DDR budgets/reset/drain/clock arithmetic; no HLS RTL result'),indent=2)+'\n')

if __name__=='__main__':main()
