"""Run the native executable with process-local MinGW DLL search paths."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
program = root / 'build/native/zynq-slam.exe'
if not program.is_file():
    raise SystemExit('Build first with scripts/check.py')
env = os.environ.copy()
system = env.get('SystemRoot', 'C:/Windows')
env['PATH'] = 'C:/Users/dmsun/mingw/mingw64/bin;' + system + '/System32;' + system
raise SystemExit(subprocess.call([str(program), *sys.argv[1:]], cwd=root, env=env))
