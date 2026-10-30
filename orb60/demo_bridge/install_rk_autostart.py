"""Install RK user startup files without interrupting an active mapping session."""
import argparse
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('deployment', type=Path)
    args = parser.parse_args()
    root = args.deployment.resolve()
    for relative in ['run_rk_controller.sh', 'run_rk_viewer.sh', 'rk_autostart.py', 'rk.local.json']:
        if not (root / relative).is_file():
            raise FileNotFoundError(root / relative)
    units = Path.home() / '.config/systemd/user'
    desktop = Path.home() / '.config/autostart'
    units.mkdir(parents=True, exist_ok=True)
    desktop.mkdir(parents=True, exist_ok=True)
    # Generated files contain this installation's paths, never baked-in source paths.
    unit = units / 'orb-demo-controller.service'
    unit.write_text('[Unit]\nDescription=ORB Studio RK mapping controller\n'
                    'StartLimitIntervalSec=60\nStartLimitBurst=5\n\n[Service]\n'
                    'Type=simple\nExecStart=/bin/sh "' + str(root / 'run_rk_controller.sh') + '" "' + str(root) + '"\n'
                    'Restart=on-failure\nRestartSec=5\nTimeoutStopSec=30\n\n'
                    '[Install]\nWantedBy=default.target\n')
    launcher = root / 'start_desktop.sh'
    launcher.write_text('#!/bin/sh\nset -eu\nroot=' + shlex.quote(str(root)) + '\n'
                        'mkdir -p "$root/gui_runtime"\n'
                        'exec 9>"$root/gui_runtime/autostart.lock"\n'
                        'flock -n 9 || exit 0\n'
                        'test ! -f "$root/gui_runtime/autostart.log" || '
                        'mv -f "$root/gui_runtime/autostart.log" "$root/gui_runtime/autostart.previous.log"\n'
                        'exec /usr/bin/python3 -u "$root/rk_autostart.py" "$root" '
                        '>>"$root/gui_runtime/autostart.log" 2>&1\n')
    entry = desktop / 'orb-studio.desktop'
    entry.write_text('[Desktop Entry]\nType=Application\nName=ORB Studio\n'
                     'Comment=Camera control and independent point-cloud windows\n'
                     'Exec=/bin/sh "' + str(launcher) + '"\nTerminal=false\n'
                     'X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    # Do not restart/adopt the controller currently collecting the user's map.
    subprocess.run(['systemctl', '--user', 'enable', unit.name], check=True)
    subprocess.run(['systemd-analyze', '--user', 'verify', str(unit)], check=True)
    subprocess.run(['/bin/sh', '-n', str(launcher)], check=True)
    print('Enabled controller at user-manager startup and ORB Studio at desktop login.')
    print('Existing mapping and windows were left running.')


if __name__ == '__main__':
    main()
