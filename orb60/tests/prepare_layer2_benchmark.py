"""True eight-level inputs for cycle measurement, using the independent oracle.

No DUT, generated ROM or PS implementation is imported. Noise is resized through
the same pyramid as a real frame; independent noise per level is not a frame.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import cv2
import numpy as np
from oracle import WIDTHS, HEIGHTS, BUDGETS, packed_image, front, gaussian, resize


def prepare(image_path, output):
    output.mkdir(parents=True, exist_ok=False)
    normal = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if normal is None or normal.shape != (720, 960):
        raise ValueError('Benchmark requires the frozen 960x720 grayscale image')
    state = 0x60A32026
    noise = bytearray(960 * 720)
    for i in range(len(noise)):
        state = (state * 1664525 + 1013904223) & 0xffffffff
        noise[i] = state >> 24
    pressure = np.frombuffer(noise, dtype=np.uint8).reshape(720, 960)
    frames = (('historical_real_image', normal), ('noise_pyramid', pressure),
              ('zero_pyramid', np.zeros_like(normal)))
    cases = []
    metadata = bytearray(struct.pack('<4I', 0x60B20001, 1, len(frames), len(frames)*8))
    for frame, (label, raw) in enumerate(frames):
        total_selected = total_candidates = 0
        for level in range(8):
            assert raw.shape == (HEIGHTS[level], WIDTHS[level])
            test = (level, -1, 20, 7, 1, 1000, 0)
            summary, points = front(raw, test)
            smaller = resize(raw, level) if level < 7 else None
            name = f'f{frame}_l{level}'
            chosen = bytearray(b'\xa5' * 16000)
            for j, point in enumerate(points):
                chosen[16*j:16*(j+1)] = struct.pack('<4i', *point)
            payloads = {'input': packed_image(raw), 'blur': packed_image(gaussian(raw), True),
                        'resize': packed_image(smaller, True), 'points': bytes(chosen),
                        'summary': struct.pack('<I12i3I', *summary)}
            for suffix, data in payloads.items():
                (output/f'{name}_{suffix}.bin').write_bytes(data)
            metadata.extend(struct.pack('<8I', frame, level, WIDTHS[level], HEIGHTS[level],
                                        BUDGETS[level], 20, 7, 1))
            cases.append(dict(frame=frame, label=label, level=level, name=name,
                              candidates=summary[2], selected=summary[3]))
            total_selected += summary[3]
            total_candidates += summary[2]
            raw = smaller
        print(f'LAYER2_BENCH_ORACLE frame={frame} label={label} candidates={total_candidates} '
              f'selected={total_selected}', flush=True)
    (output/'cases.bin').write_bytes(metadata)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.bin')}
    result = dict(scope='Independent Python oracle; real resize pyramids, default 20/7 thresholds',
                  input=str(image_path), input_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
                  cases=cases, sha256=hashes)
    (output/'vectors.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.input, args.output)
