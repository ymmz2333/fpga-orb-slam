#!/usr/bin/env python3
"""Resolve board apt packages; download on PC with apt-metadata SHA256 checks."""
import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import shlex
import subprocess
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['manifest', 'download'])
parser.add_argument('directory', type=pathlib.Path)
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
manifest = args.directory/'packages.json'
if args.action == 'manifest':
    output = subprocess.check_output(['apt-get','--print-uris','--yes','--download-only',
                                      '--no-install-recommends','install','libgtk-3-dev'], text=True)
    packages = []
    for line in output.splitlines():
        if not line.startswith("'http"):
            continue
        url, filename, size, md5 = shlex.split(line)
        name = filename.split('_')[0]
        records = subprocess.check_output(['apt-cache','show',name], text=True).split('\n\n')
        record = next(dict(row.split(': ',1) for row in block.splitlines() if ': ' in row)
                      for block in records if 'MD5sum: '+md5.split(':')[1] in block)
        packages.append(dict(url=url.replace('http:','https:',1),filename=filename,
                             size=int(size),sha256=record['SHA256'],package=name,version=record['Version']))
    manifest.write_text(json.dumps(packages,indent=2))
    print('GTK_PACKAGES count=%d bytes=%d' % (len(packages),sum(p['size'] for p in packages)))
else:
    packages = json.loads(manifest.read_text())
    def download(package):
        target = args.directory/package['filename']
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=package['sha256']:
            with urllib.request.urlopen(package['url'],timeout=60) as response:
                data = response.read()
            if len(data)!=package['size'] or hashlib.sha256(data).hexdigest()!=package['sha256']:
                raise RuntimeError('APT integrity check failed: '+package['package'])
            target.write_bytes(data)
        return package['package']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        done = list(pool.map(download,packages))
    print('GTK_DOWNLOAD_PASS packages=%d all_sha256_verified=true' % len(done))
