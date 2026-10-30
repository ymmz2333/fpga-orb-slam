"""Freeze Python-oracle AXI vectors, cross-checking the independent C++ exporter."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from oracle import (FRONT_CASES, FRONT2_CASES, RESIZE_CASES, GAUSSIAN_CASES, WIDTHS, HEIGHTS,
                    BUDGETS, pixels, packed_image, front, resize, gaussian)


def prepare(job, output, kernel='all'):
    output.mkdir(parents=True, exist_ok=False)
    front_cases = FRONT2_CASES if kernel == 'front2' else FRONT_CASES
    reference = (job / ('inputs/front2_vectors.inc' if kernel == 'front2' else 'inputs/front_vectors.inc')).read_text()
    summary_text, points_text = reference.split('static const fastv2::Point')
    cpp_summaries = [list(map(int, re.findall(r'-?\d+', row)))
                     for row in re.findall(r'\{([^{}]+)\}', summary_text)]
    cpp_points = []
    for row in points_text.splitlines()[1:-1]:
        cpp_points.append([tuple(map(int, p.split(','))) for p in re.findall(r'\{(-?\d+,-?\d+,-?\d+,-?\d+)\}', row)])
    cases = []
    cache = {}
    selections = (('front2', front_cases),) if kernel == 'front2' else (('front', front_cases), ('resize', RESIZE_CASES), ('gaussian', GAUSSIAN_CASES))
    assert len(cpp_summaries) == len(front_cases) and len(cpp_points) == len(front_cases)
    for kernel, tests in selections:
        is_front = kernel in ('front', 'front2')
        for index, test in enumerate(tests):
            level, pattern = test[:2]
            valid = 0 <= level < (7 if kernel == 'resize' else 8)
            key = (is_front, level, pattern)
            if valid and key not in cache:
                cache[key] = pixels(level, pattern, front=is_front)
            image = cache[key] if valid else None
            item = {'kernel': kernel, 'index': index, 'level': level, 'pattern': pattern}
            name = f'{kernel}_{index:02}'
            (output / f'{name}_input.bin').write_bytes(packed_image(image))
            if is_front:
                summary, points = front(image, test)
                assert summary == cpp_summaries[index], (index, summary, cpp_summaries[index])
                expected_cpp = cpp_points[index] if points else []
                assert points == expected_cpp, f'Python/C++ point mismatch case {index}'
                record = bytearray(b'\xa5' * 16000)
                for i, point in enumerate(points):
                    record[i * 16:(i + 1) * 16] = struct.pack('<4i', *point)
                (output / f'{name}_points.bin').write_bytes(record)
                (output / f'{name}_summary.bin').write_bytes(struct.pack('<I12i3I', *summary))
                item.update(status=summary[1], selected=summary[3], candidates=summary[2],
                            args=[WIDTHS[level], HEIGHTS[level], BUDGETS[level] + test[6], *test[2:6]])
            else:
                expected = resize(image, level) if valid and kernel == 'resize' else gaussian(image) if valid else None
                (output / f'{name}_output.bin').write_bytes(packed_image(expected, output=True))
                item.update(status=0 if valid else 1, active_bytes=expected.size if valid else 0)
            item['name'] = name
            cases.append(item)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.bin')}
    (output / 'vectors.json').write_text(json.dumps({'cases': cases, 'sha256': hashes,
        'front_python_cpp_exact': len(front_cases)}, indent=2) + '\n')
    print(f'ORB60_PYTHON_ORACLE_PASS front_cpp_crosscheck={len(front_cases)} transactions={len(cases)}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--kernel', choices=('all', 'front2'), default='all')
    args = parser.parse_args()
    prepare(args.job, args.output, args.kernel)
