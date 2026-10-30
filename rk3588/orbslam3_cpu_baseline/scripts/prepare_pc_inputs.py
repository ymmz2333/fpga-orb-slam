#!/usr/bin/env python3
"""Copy the approved three datasets from Windows originals and retain hash evidence."""
import argparse
import csv
import hashlib
import json
import pathlib
import shutil
import zipfile

TELLO = ('flight_20261004T184929_998838_6bb93c56', 'flight_20261004T200648_509768_918b85a4')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-project', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = pathlib.Path(args.windows_project)
    workspace = source.parents[1]
    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []

    def copy_checked(src, dst, dataset, expected=None, board_expected=None):
        value = sha(src)
        if expected is not None and value != expected:
            raise RuntimeError('PC original hash mismatch: ' + str(src))
        if board_expected is not None and value != board_expected:
            raise RuntimeError('Archived board hash mismatch: ' + str(src))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(src, dst)
        if sha(dst) != value:
            raise RuntimeError('WSL copy hash mismatch: ' + str(dst))
        rows.append(dict(dataset=dataset, path=str(dst.relative_to(output)), sha256=value,
                         pc_source_match=True, board_sha256=board_expected or '',
                         board_sha256_match=True if board_expected is not None else ''))

    with (source / 'reports/b3_precheck/P1_full_20261005/raw/png_hashes.csv').open(newline='') as stream:
        board = {(r['dataset'], r['timestamp_ns']): r['actual_sha256'] for r in csv.DictReader(stream) if r['round'] == '1'}
    manifest = json.loads((source / 'reports/c1/dataset_manifest.json').read_text())
    clips = {item['dataset']: item for item in manifest['clips']}
    for dataset in TELLO:
        src = source / 'runtime/c/datasets/TT_C1_01' / dataset
        info = clips[dataset]
        if sha(src / 'frames.csv') != info['frames_csv_sha256'] or sha(src / 'timestamps.txt') != info['timestamps_sha256']:
            raise RuntimeError('Archived Tello metadata mismatch: ' + dataset)
        frames = list(csv.DictReader((src / 'frames.csv').open(newline='')))
        stamps = [int(line) for line in (src / 'timestamps.txt').read_text().splitlines() if line.strip()]
        if len(frames) != info['expected_frames'] or stamps != [int(r['timestamp_ns']) for r in frames] or any(a >= b for a, b in zip(stamps, stamps[1:])):
            raise RuntimeError('Tello timestamp/frame indexing mismatch: ' + dataset)
        for frame in frames:
            ns = frame['timestamp_ns']
            copy_checked(src / frame['image'], output / dataset / frame['image'], dataset,
                         frame['sha256'], board[(dataset, ns)])
        for filename in ('frames.csv', 'timestamps.txt', 'dataset.json'):
            copy_checked(src / filename, output / dataset / filename, dataset)
    euroc = workspace / 'data/euroc/MH_01_easy'
    with zipfile.ZipFile(workspace / 'MH_01_easy.zip') as archive:
        for name in archive.namelist():
            if name.endswith('/') or not (name.startswith('mav0/cam0/') or name.startswith('mav0/state_groundtruth_estimate0/')):
                continue
            relative = pathlib.PurePosixPath(name)
            if '..' in relative.parts or relative.is_absolute():
                raise RuntimeError('Unsafe archive entry')
            # ZIP checks its original CRC while reading; source SHA comparison is independent.
            expected = hashlib.sha256(archive.read(name)).hexdigest()
            copy_checked(euroc / relative, output / 'MH01' / relative, 'MH01', expected)
    stamps_source = source / 'reports/a2/MH01.txt'
    copy_checked(stamps_source, output / 'MH01/timestamps.txt', 'MH01',
                 board_expected=json.loads((source / 'reports/a2/dataset.json').read_text())['timestamps_sha256'])
    stamps = (output / 'MH01/timestamps.txt').read_text().splitlines()
    image_count = len(list((output / 'MH01/mav0/cam0/data').glob('*.png')))
    if image_count != 3682 or len(stamps) != 3682:
        raise RuntimeError('MH01 frame count mismatch')
    with (output / 'input_hashes.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = dict(platform='x86 PC / WSL2', copied_files=len(rows), pc_copy_hash_mismatches=0,
                  tello_board_image_hashes_matched=sum(r['dataset'] in TELLO and r['board_sha256_match'] is True for r in rows),
                  euroc_images=image_count, euroc_pc_zip_entry_hashes_matched=True,
                  euroc_board_per_image_hashes='PENDING: not present in the current local board archive',
                  intrinsics_label='借用内参，未本机标定', source_policy='PC originals only; no board camera-data transfer')
    (output / 'input_verification.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print('PC_INPUT_COPY_CHECKED ' + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
