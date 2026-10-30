"""Read-only verification of an exported handoff; never runs board/build commands."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def safe_path(root, name):
    relative = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe manifest path: ' + name)
    path = root.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
        raise ValueError('Missing, linked or external file: ' + name)
    return path


def verify(root):
    root = root.resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    hashes = manifest['file_sha256']
    if len({name.casefold() for name in hashes}) != len(hashes):
        raise ValueError('Case-colliding files in manifest')
    for name, expected in hashes.items():
        if digest(safe_path(root, name)) != expected:
            raise ValueError('HASH_MISMATCH: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(hashes) | {'manifest.json', 'SHA256SUMS'}:
        raise ValueError('Unexpected/missing package files: ' + repr(actual ^ (set(hashes) | {'manifest.json', 'SHA256SUMS'})))
    sums = {}
    for line in (root / 'SHA256SUMS').read_text(encoding='ascii').splitlines():
        expected, name = line.split('  ', 1)
        if name in sums:
            raise ValueError('Duplicate SHA256SUMS entry')
        sums[name] = expected
    expected_sums = dict(hashes, **{'manifest.json': digest(root / 'manifest.json')})
    if sums != expected_sums:
        raise ValueError('SHA256SUMS/manifest disagreement')
    counts = {}
    for binding in manifest['verified_bindings']:
        if hashes.get(binding['package_path']) != binding['sha256']:
            raise ValueError('Build/source binding mismatch: ' + binding['package_path'])
        counts[binding['role']] = counts.get(binding['role'], 0) + 1
    # Original deployment manifests are retained byte-for-byte inside this package.
    for name in ['artifacts/camera_runtime/SHA256SUMS',
                 'artifacts/camera_runtime/s1-controls/SHA256SUMS',
                 'artifacts/camera_runtime/HANDOFF_SHA256SUMS']:
        parent = root / 'artifacts/camera_runtime'
        for line in (root / name).read_text(encoding='ascii').splitlines():
            expected, relative = line.split('  ', 1)
            target = safe_path(parent, relative)
            if digest(target) != expected:
                raise ValueError('Runtime deployment checksum mismatch: ' + relative)
    return dict(status='PASS_HANDOFF_INTEGRITY', files=len(hashes),
                bytes=sum((root / name).stat().st_size for name in hashes),
                verified_bindings=counts,
                scope='File completeness and historical source/artifact identity only; no new compile, simulation or board test',
                live_camera_30fps_accepted=False, tracking_quality_accepted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=True, indent=2))
