"""Persist a local fixed map, calibration and optional same-map RGB blocks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from orb60.demo_bridge.calibration import read
from orb60.demo_bridge.export_map import prepare
from orb60.demo_bridge.map_bundle import seal, validate
from .dense_fusion import save


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):value.update(block)
    return value.hexdigest()


def create(source, camera, executable, output, dense_run=None):
    source, camera, output = Path(source).resolve(), Path(camera).resolve(), Path(output).resolve()
    if output.exists():raise ValueError('Fresh fixed-map bundle required')
    read(camera.read_bytes())
    output.mkdir(parents=True)
    try:
        selection = prepare(source, output/'export')
        map_id = int((source/'map_id.txt').read_text())
        seal(output/'export', camera, map_id)
        info = validate(output/'export', camera.read_bytes())
        shutil.copy2(camera, output/'camera.csv')
        command = [str(Path(executable).resolve()), 'import', str(output/'camera.csv'),
                   str(output/'export'), str(output/'map.zslmap')]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        (output/'import.log').write_text(result.stdout+result.stderr, encoding='utf-8')
        if result.returncode or 'KV260_FIXED_MAP_IMPORT_ROUNDTRIP_PASS' not in result.stdout:
            raise RuntimeError('Native map import/roundtrip failed; inspect import.log')
        dense = None
        if dense_run is not None:
            run = Path(dense_run).resolve()
            # Do not attach another reconstruction just because its map number
            # is also zero. Require the exact immutable mapping export bytes.
            for name in ('points.csv','keyframes.csv','observations.csv','map_id.txt'):
                if digest(run/'tracking/map'/name) != digest(source/name):
                    raise ValueError('Dense map belongs to a different SLAM export: '+name)
            report = json.loads((run/'dense/status.json').read_text())
            final = json.loads((run/'dense/blocks/final_pose_update.json').read_text())
            if report['status'] != 'COMPLETED' or final['map_id'] != map_id or not final['accepted']:
                raise ValueError('Dense map final pose update is incomplete')
            destination = output/'dense_blocks'; destination.mkdir()
            for stem in final['accepted']:
                if '/' in stem or '\\' in stem or stem.startswith('.'):
                    raise ValueError('Unsafe RGB block name')
                for suffix in ('.final.bin','.final.json'):
                    shutil.copy2(run/'dense/blocks'/(stem+suffix), destination/(stem+suffix))
            dense = dict(map_id=map_id, blocks=final['accepted'], backend=report['backend'],
                         hardware_inference_verified=report.get('hardware_inference_verified',False))
        files = {p.relative_to(output).as_posix():digest(p) for p in sorted(output.rglob('*')) if p.is_file()}
        manifest = dict(format='KV260_FIXED_MAP_V1', map=info, selection=selection,
                        source_export_sha256={p.name:digest(p) for p in source.iterdir() if p.is_file()},
                        geometry='Original SLAM world; Twc; unmeasured monocular scale',
                        dense=dense, files=files)
        save(output/'bundle.json',manifest)
        load(output,camera)
        return manifest
    except BaseException as error:
        save(output/'FAILED.json',dict(error=repr(error)))
        raise


def load(folder, camera):
    folder = Path(folder).resolve()
    if (folder/'FAILED.json').exists():raise ValueError('Incomplete/failed fixed-map bundle')
    meta = json.loads((folder/'bundle.json').read_text())
    if meta.get('format') != 'KV260_FIXED_MAP_V1':raise ValueError('Unsupported fixed-map bundle')
    for name, expected in meta['files'].items():
        path = folder/name
        if path.resolve().parent != folder and folder not in path.resolve().parents:
            raise ValueError('Fixed-map path escapes bundle')
        if path.is_symlink() or digest(path) != expected:raise ValueError('Fixed-map checksum mismatch: '+name)
    camera_bytes = Path(camera).read_bytes()
    if camera_bytes != (folder/'camera.csv').read_bytes():raise ValueError('Fixed-map camera bytes differ')
    validate(folder/'export',camera_bytes)
    if not (folder/'map.zslmap').is_file():raise ValueError('Serialized fixed map missing')
    return meta


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','camera','executable','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--dense-run',type=Path)
    args=parser.parse_args()
    result=create(args.source,args.camera,args.executable,args.output,args.dense_run)
    print(json.dumps(result['map']))
