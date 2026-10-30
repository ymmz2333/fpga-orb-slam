"""Small, folder-local Icarus runner for course testbenches."""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--action', choices=['check', 'compile', 'sim', 'wave', 'gtkwave'])
    p.add_argument('--file', required=True)
    p.add_argument('--top', default='')
    p.add_argument('--timeout', type=int, default=30)
    for tool in ['iverilog', 'vvp', 'gtkwave']:
        p.add_argument('--' + tool, required=True)
    a = p.parse_args()
    current = Path(a.file).resolve()
    if not current.is_file():
        raise ValueError('Open a saved Verilog file in your question folder first.')
    folder = current.parent
    build = folder / '.sim'
    manifest = build / 'latest.json'
    if a.action in ['wave', 'gtkwave']:
        if not manifest.exists():
            raise ValueError('No waveform for this question. Run simulation first.')
        wave = Path(json.loads(manifest.read_text())['wave'])
        if not wave.is_file():
            raise ValueError('Waveform was removed. Run simulation again.')
        if a.action == 'wave':
            subprocess.run([shutil.which('code.cmd') or 'code', '--reuse-window', str(wave)], check=True)
        else:
            subprocess.Popen([a.gtkwave, str(wave)])
        print('Opened:', wave)
        return
    if a.action != 'check':
        manifest.unlink(missing_ok=True)
    sources = sorted(s for s in folder.iterdir() if s.suffix.lower() in ('.v', '.sv', '.tb'))
    # Remove comments before looking for module declarations; explicit --top is
    # available for unusual naming or preprocessor-heavy testbenches.
    modules = {}
    for source in sources:
        text = source.read_text(encoding='utf-8-sig')
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
        modules[source] = re.findall(r'\bmodule\s+(?:automatic\s+)?([A-Za-z_][\w$]*)', text)
    top = a.top
    if not top:
        def is_tb(name):
            return name.lower().endswith(('_tb', '_testbench')) or name.lower().startswith('tb_')
        preferred = [n for n in modules.get(current, []) if is_tb(n)]
        if not preferred and current.suffix.lower() == '.tb' and len(modules.get(current, [])) == 1:
            preferred = modules[current]
        candidates = preferred or [n for names in modules.values() for n in names if is_tb(n)]
        if not candidates:
            candidates = [n for s in sources if s.suffix.lower() == '.tb' for n in modules[s]]
        if len(candidates) != 1:
            raise ValueError('Cannot select a unique TB. Keep one TB per folder, open its file, or use -Top module_name.')
        top = candidates[0]
    if not re.fullmatch(r'[A-Za-z_][\w$]*', top):
        raise ValueError('Invalid top module name.')
    selected = [s for s in sources if top in modules[s] or not any(
        n.lower().endswith(('_tb', '_testbench')) or n.lower().startswith('tb_') for n in modules[s])]
    if a.action == 'check':
        result = subprocess.run([a.iverilog, '-g2012', '-Wall', '-I', str(folder),
                                 '-s', top, '-t', 'null', *map(str, selected)], cwd=folder)
        if result.returncode:
            raise ValueError('CHECK FAILED. Check the diagnostic above.')
        print('CHECK OK')
        return
    build.mkdir(exist_ok=True)
    manifest.unlink(missing_ok=True)  # Never reopen a stale result after a failed run.
    wave = build / 'wave.vcd'
    wave.unlink(missing_ok=True)
    existing_wave = build / 'simulation.vcd'
    existing_wave.unlink(missing_ok=True)
    wrapper = build / 'exam_wave.v'
    wrapper.write_text('`timescale 1ns/1ps\nmodule __exam_wave;\ninitial begin\n'
                       f'$dumpfile("wave.vcd"); $dumpvars(0, {top});\nend\nendmodule\n')
    output = build / 'simulation.vvp'
    # Exclude other TB files when a specific TB is selected. Keep helper modules
    # inside the selected TB (the supplied traffic tests depend on this).
    command = [a.iverilog, '-g2012', '-Wall', '-I', str(folder), '-s', top,
               '-s', '__exam_wave', '-o', str(output), *map(str, selected), str(wrapper)]
    print('TOP:', top, '\nSOURCES:', ', '.join(s.name for s in selected), flush=True)
    result = subprocess.run(command, cwd=folder)
    if result.returncode:
        raise ValueError('COMPILE FAILED. Check the error above; add your DUT .v files beside the TB.')
    print('COMPILE OK', flush=True)
    if a.action == 'compile':
        return
    try:
        result = subprocess.run([a.vvp, str(output)], cwd=build, capture_output=True,
                                timeout=a.timeout, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            print(exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout)
        raise ValueError(f'SIM TIMEOUT ({a.timeout}s). Check clocks, stop conditions and DUT logic.')
    log = result.stdout + result.stderr
    (build / 'simulation.log').write_text(log, encoding='utf-8')
    print(log, end='')
    # Some course TBs already choose simulation.vcd; Icarus accepts only one
    # dumpfile, so record whichever was actually produced.
    waves = [w for w in build.glob('*.vcd') if w.stat().st_size > 0]
    actual = max(waves, key=lambda w: w.stat().st_mtime) if waves else None
    if actual:
        manifest.write_text(json.dumps({'wave': str(actual), 'top': top}))
        print('WAVE:', actual)
    if result.returncode or re.search(r'CHECK_FAILED|COURSE_CHECKS_FAILED|COURSE_TIMEOUT|FATAL:|ERROR:', log):
        raise ValueError('SIM/CHECK FAILED. Waveform is available for debugging.')
    if not actual:
        raise ValueError('Simulation exited without a waveform.')
    if 'COURSE_CHECKS_PASSED' in log:
        print('SIM OK: course self-checks passed.')
    else:
        print('SIM FINISHED: this TB reported no self-check verdict; inspect the waveform.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
