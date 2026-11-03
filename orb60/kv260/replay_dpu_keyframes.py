"""Actual KV260 DPU reconstruction from saved native keyframes and poses.

This component replay does not run PL or repeat PS mapping. It preserves the
online entry's acceptance requirements and identifies the saved mapping source.
"""
import argparse
import json
from pathlib import Path
import platform
import shutil
from .dense_service import run
from .dense_fusion import save
from .frame_store import FrameStore


def replay(source, output, model, placement, preflight, selection, camera):
    source, output = Path(source).resolve(), Path(output).resolve()
    if platform.machine() != 'aarch64':
        raise ValueError('Actual KV260 required; no reference fallback')
    if not (source/'NATIVE_COMPLETE').is_file() or not (source/'tracking/map/EXPORT_COMPLETE').is_file():
        raise ValueError('Completed saved native map required')
    original = json.loads((source/'network_mapping.json').read_text())
    if original.get('frontend') != 'actual_zynq7015_PL' or original.get('cpu_orb_calls') != 0:
        raise ValueError('Saved source must contain physical 7015 features and no CPU ORB')
    if output.exists():
        raise ValueError('Fresh reconstruction directory required')
    metas = sorted((source/'dense/color_poses').glob('f*.json'), key=lambda p:int(p.stem[1:]))
    if len(metas) < 2:
        raise ValueError('At least two actual keyframes required')
    store = FrameStore(source/'dense/rgb_cache')
    for path in metas:
        meta = json.loads(path.read_text())
        if meta.get('anchor_kind') != 'slam_keyframe':
            raise ValueError('Expected actual SLAM keyframe')
        store.read(meta)
    output.mkdir(parents=True)
    (output/'tracking').mkdir()
    shutil.copytree(source/'tracking/map', output/'tracking/map')
    shutil.copy2(source/'tracking/frames.csv', output/'tracking/frames.csv')
    shutil.copytree(source/'dense/color_poses', output/'dense/color_poses')
    shutil.copytree(source/'dense/rgb_cache', output/'dense/rgb_cache')
    config = {'backend':'dpu', 'model':str(Path(model).resolve()), 'placement':str(Path(placement).resolve()),
              'preflight':str(Path(preflight).resolve()), 'selection':str(Path(selection).resolve()),
              'camera':str(Path(camera).resolve()), 'keyframes_only':True, 'port':18789,
              'linger_after_complete':False}
    save(output/'depth_config.json', config)
    report = {'status':'RUNNING', 'depth_backend':'actual_KV260_DPU', 'mapping_reexecuted':False,
              'pl_executed_in_this_replay':False, 'source_run':source.name,
              'source_mapping':original, 'selected_keyframes':len(metas),
              'scope':'Component reconstruction using saved physical7015 features, native PS poses and paired RGB; no live mapping/FPS claim'}
    save(output/'COMPONENT.json', report)
    stop = output/'stop_dense'
    stop.touch()  # All selected RGB and poses are already available; drain once.
    try:
        dense = run(config, output, stop)
        if not dense.get('hardware_inference_verified') or dense.get('status') != 'COMPLETED':
            raise RuntimeError('Actual DPU inference and complete colored reconstruction required')
        if not dense.get('maps') or any(m['points'] <= 0 for m in dense['maps']):
            raise RuntimeError('Empty colored reconstruction')
        report.update(status='ACTUAL_DPU_SAVED_POSE_RECONSTRUCTION_PASS', dense=dense)
    except BaseException as error:
        report.update(status='FAILED', error=repr(error))
        raise
    finally:
        save(output/'COMPONENT.json', report)
    print(json.dumps({'status':report['status'], 'depth_frames':dense['depth_frames'], 'maps':dense['maps']}))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','model','placement','preflight','selection','camera'):
        p.add_argument('--'+name, type=Path, required=True)
    replay(**vars(p.parse_args()))
