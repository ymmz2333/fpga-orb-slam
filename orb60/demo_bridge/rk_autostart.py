"""Desktop-login entry point. Reuse this deployment only; never duplicate it."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def running_with(argument):
    expected = os.fsencode(str(argument))
    found = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / 'cmdline').read_bytes().split(b'\0')
        except (OSError, PermissionError):
            continue
        if expected in args:
            found.append(int(process.name))
    return found


def main():
    root = Path(sys.argv[1]).resolve()
    viewer = root / 'workspace/orb60/viewer/app.py'
    if running_with(viewer):
        print('Existing ORB Studio window retained', flush=True)
        return 0
    if not running_with(root / 'rk.local.json'):
        subprocess.run(['systemctl', '--user', 'start', 'orb-demo-controller.service'], check=True)
    for _ in range(40):
        try:
            with urllib.request.urlopen('http://127.0.0.1:5610/status', timeout=1) as response:
                status = json.load(response)
            if 'state' in status and running_with(root / 'rk.local.json'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    else:
        raise RuntimeError('ORB controller did not become ready; inspect its systemd journal')
    os.execv('/bin/sh', ['sh', str(root / 'run_rk_viewer.sh'), str(root),
                        '--metrics', str(root / 'gui_runtime/autostart_metrics.json')])


if __name__ == '__main__':
    raise SystemExit(main())
