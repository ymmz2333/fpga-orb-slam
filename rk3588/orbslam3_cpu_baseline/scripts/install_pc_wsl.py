#!/usr/bin/env python3
"""Install the official Focal WSL image; retain logs and never reboot Windows."""
import argparse
import datetime
import hashlib
import json
import pathlib
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parents[1]
URL = 'https://releases.ubuntu.com/focal/ubuntu-20.04.6-wsl-amd64.wsl'
EXPECTED = 'a9073f3726aab9661076506603706eadf284b80a791dec3adfde8e1989906fa4'


def decode(data):
    return data.decode('utf-16-le' if data.count(b'\0') > len(data) // 8 else 'utf-8', errors='replace')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'runtime/pc/wsl_setup'
    output.mkdir(parents=True, exist_ok=True)
    state = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'status': 'STARTING', 'distro': 'Ubuntu-20.04', 'automatic_reboot': False}

    def save():
        temporary = output / 'state.json.tmp'
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(output / 'state.json')

    def command(name, argv):
        print(name, flush=True)
        result = subprocess.run(argv, capture_output=True)
        (output / (name + '.stdout.log')).write_text(decode(result.stdout), encoding='utf-8')
        (output / (name + '.stderr.log')).write_text(decode(result.stderr), encoding='utf-8')
        state[name + '_exit_code'] = result.returncode
        save()
        return result

    save()
    try:
        version = command('wsl_version', ['wsl', '--version'])
        if version.returncode:
            raise RuntimeError('WSL runtime unavailable; install WSL first (no automatic restart).')
        listed = command('distributions', ['wsl', '--list', '--quiet'])
        names = decode(listed.stdout).replace('\0', '').splitlines()
        if 'Ubuntu-20.04' not in [s.strip() for s in names]:
            if not args.install:
                state['status'] = 'NOT_INSTALLED'
                save()
                return 2
            state.update(source_url=URL, expected_sha256=EXPECTED, provenance='official_image_import')
            image = output / pathlib.PurePosixPath(URL).name
            if not image.exists():
                state['status'] = 'DOWNLOADING'
                save()
                part = image.with_suffix(image.suffix + '.part')
                with urllib.request.urlopen(URL, timeout=60) as response, part.open('wb') as target:
                    size = 0
                    while block := response.read(1024 * 1024):
                        target.write(block)
                        size += len(block)
                        state['download_bytes'] = size
                        save()
                part.replace(image)
            with image.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            state['actual_sha256'] = actual
            if actual != EXPECTED:
                raise RuntimeError('Official WSL image SHA256 mismatch; import refused.')
            state['status'] = 'IMPORTING'
            save()
            location = WORKSPACE / '.work/wsl/Ubuntu-20.04'
            location.parent.mkdir(parents=True, exist_ok=True)
            state['location'] = str(location)
            result = command('import', ['wsl', '--import', 'Ubuntu-20.04', str(location), str(image), '--version', '2'])
            if result.returncode:
                raise RuntimeError('WSL import failed; inspect import logs (restart/elevation may be required).')
        else:
            state['provenance'] = 'existing_distribution; image bytes not verified by this script'
        result = command('linux_check', ['wsl', '-d', 'Ubuntu-20.04', '-u', 'root', '--',
                                      'sh', '-c', 'cat /etc/os-release; uname -m; uname -r; free -b'])
        text = decode(result.stdout)
        if result.returncode or 'VERSION_ID="20.04"' not in text or 'x86_64' not in text:
            raise RuntimeError('Ubuntu 20.04 x86_64 startup acceptance failed.')
        state['status'] = 'SUCCEEDED'
        state['exit_code'] = 0
        print('WSL_SETUP_SUCCEEDED Ubuntu-20.04 / WSL2; PC0 dependencies and tests still pending.', flush=True)
        return 0
    except Exception as error:
        state.update(status='FAILED', exit_code=1, error=str(error))
        print('WSL_SETUP_FAILED ' + str(error), flush=True)
        return 1
    finally:
        state['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    raise SystemExit(main())
