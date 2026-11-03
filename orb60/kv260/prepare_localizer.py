"""Package the retained fixed-map PS core for an isolated KV260 native build."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def prepare(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh output required; retained sources are never overwritten')
    source = ROOT / 'zynq7015_demo'
    (output / 'src').mkdir(parents=True)
    (output / 'include/zslam').mkdir(parents=True)
    records = {}
    for name in ('math.cpp', 'pnp.cpp', 'slam.cpp', 'map_store.cpp', 'formats.cpp'):
        original = source / 'src' / name
        data = original.read_bytes()
        target = output / 'src' / name
        if name == 'formats.cpp':
            # Capture/JPEG belongs to the KV260 producer. This build accepts
            # working-image calibration only, and never decodes source cameras.
            text = data.decode('utf-8')
            old = '    if(source_geometry)cameraCrop(c.width,c.height);'
            if text.count(old) != 1:
                raise ValueError('Unsupported retained camera-format source')
            text = text.replace('#include "zslam/camera.hpp"\n', '')
            text = text.replace(old, '    if(source_geometry)throw std::runtime_error("KV260 locator requires working-image calibration");')
            target.write_text(text, encoding='utf-8', newline='\n')
        else:
            target.write_bytes(data)
        records[str(original.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    for name in ('slam.hpp', 'math.hpp', 'formats.hpp', 'filesystem.hpp',
                 'spatial_bins.hpp', 'motion.hpp', 'profiling.hpp', 'bridge_wire.hpp'):
        original = source / 'include/zslam' / name
        shutil.copy2(original, output / 'include/zslam' / name)
        records[str(original.relative_to(ROOT))] = hashlib.sha256(original.read_bytes()).hexdigest()
    shutil.copytree(source / 'vendor/opencv_p3p', output / 'vendor/opencv_p3p')
    for original in sorted((source / 'vendor/opencv_p3p').rglob('*')):
        if original.is_file():
            records[str(original.relative_to(ROOT))] = hashlib.sha256(original.read_bytes()).hexdigest()
    for name in ('CMakeLists.txt', 'localize_main.cc'):
        shutil.copy2(ROOT / 'orb60/kv260/localization' / name, output / name)
    manifest = dict(boundary='PS software: retained matching and geometry; no ORB extractor or FPGA driver',
                    retained_source_sha256=records,
                    files={p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(output.rglob('*')) if p.is_file()})
    (output / 'KV260_LOCALIZER_SOURCE.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(prepare(parser.parse_args().output))
