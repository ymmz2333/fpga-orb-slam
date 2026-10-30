"""Read a completed synthesis checkpoint using the isolated 2018.3 profile."""
from pathlib import Path
import argparse
import datetime
import os
import sys
from synth_pl_2018 import run_profile, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    a = parser.parse_args()
    root = a.run.resolve()
    checkpoint = root / 'vivado/s_wrapper_synth.dcp'
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    output = root / ('inspection_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir(exist_ok=False)
    script = output / 'analyze.tcl'
    script.write_text('''if {[version -short] ne "2018.3"} {error "Requires Vivado 2018.3"}
set_param general.maxThreads 1
open_checkpoint {%s}
report_timing -max_paths 20 -nworst 1 -slack_lesser_than 0 -file negative_setup_paths.rpt
report_methodology -file methodology.rpt
write_xdc -exclude_physical constraints.xdc
help config_ip_cache
close_design
exit 0
''' % checkpoint.as_posix())
    result = {'status': 'RUNNING', 'checkpoint': str(checkpoint),
              'scope': 'read-only checkpoint reports; no implementation or hardware actions'}
    write_json(output / 'status.json', result)
    print('Analysis', output, flush=True)
    rc = run_profile(['-mode','batch','-notrace','-source',script,
                      '-log',output/'vivado.log','-journal',output/'vivado.jou'],
                     output, output/'console.log', dict(os.environ))
    result.update(status='PASS' if rc == 0 else 'FAIL', returncode=rc)
    write_json(output/'status.json', result)
    print(result['status'], output, flush=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
