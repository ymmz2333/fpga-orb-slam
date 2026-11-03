"""Seal a completed stable KV260 map for the production 7015 PS importer.

No board programming or installation is performed. The KV260 serialized map is
never reused as a 7015 native map: the receiver must perform its own import and
byte-exact native roundtrip. Dense display data is optional and never used for
feature matching.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import tarfile

from orb60.demo_bridge.export_map import prepare
from orb60.demo_bridge.map_bundle import seal, validate
from .map_continuity import audit
from .mapping_acceptance import evaluate


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_source(run, acceptance_review=None):
    run = Path(run).resolve()
    control = run.with_name(run.name + '_control')
    result = json.loads((control / 'RESULT.json').read_text(encoding='utf-8'))
    if result.get('status') != 'ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS' and acceptance_review is None:
        raise ValueError('Completed stable-map component acceptance required; failed trials are immutable')
    if acceptance_review is not None and result.get('status') not in ('ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS','FAILED_TARGET_GATES'):
        raise ValueError('A user quality review cannot accept a failed/incomplete execution')
    mapping=result.get('mapping')
    if (result.get('frontend') != 'actual_zynq7015_PL' or not isinstance(mapping,dict) or
        mapping.get('mapping')!='KV260_PS' or mapping.get('frontend')!='actual_zynq7015_PL' or mapping.get('cpu_orb_calls')!=0):
        raise ValueError('Actual two-board map source required')
    with (run / 'tracking/frames.csv').open(newline='') as f:
        frames = list(csv.DictReader(f))
    if len(frames) != result['frames_requested'] or len(frames) != result['frame_checks']['frames']:
        raise ValueError('Whole-source frame count differs from accepted result')
    if result.get('source_frames_total') != len(frames):
        raise ValueError('A prefix replay cannot be published as the whole-video map')
    if not frames or any(int(r['source_frame_id']) != i or int(r['cpu_orb_calls']) for i, r in enumerate(frames)):
        raise ValueError('Missing/reordered source frame or CPU ORB fallback')
    first = next((i for i, r in enumerate(frames) if int(r['pose_valid'])), None)
    if first is None: raise ValueError('No initialized map')
    checks = dict(valid_after_initialization=sum(int(r['pose_valid']) for r in frames[first:]) / len(frames[first:]))
    if checks['valid_after_initialization'] != result['frame_checks']['valid_after_initialization']:
        raise ValueError('Saved frame validity differs from acceptance result')
    continuity = audit(frames, (control / 'native.log').read_text(encoding='utf-8', errors='replace'))
    profile=result['acceptance_profile'];review=None
    if acceptance_review is not None:
        review=json.loads(Path(acceptance_review).read_text(encoding='utf-8'))
        actual_tail=continuity['tracking_loss_segments']
        if (review.get('format')!='KV260_USER_MAPPING_REVIEW_V1' or
            review.get('decision')!='ACCEPT_CURRENT_MAP_WITH_INVALID_TAIL' or
            review.get('result_sha256')!=digest(control/'RESULT.json') or
            review.get('approved_loss_segments')!=actual_tail or
            review.get('frames')!=len(frames) or review.get('first_valid_frame')!=first or
            review.get('valid_poses')!=sum(int(r['pose_valid']) for r in frames) or
            review.get('acceptance_profile')!='stable_map_5fps_tail84'):
            raise ValueError('Explicit user review does not match this exact recorded run')
        profile=review['acceptance_profile']
    checks['frames']=len(frames)
    accepted = evaluate(profile, checks, continuity, result['timings'],
                        profiling=result['profiling'], kernel_tainted=result['kernel_tainted'],
                        last_pose_valid=bool(int(frames[-1]['pose_valid'])))
    if accepted['status'] != 'ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS':
        raise ValueError('Recomputed stable map gates failed')
    if any(result['frame_checks'][k] for k in ('source_identity_mismatches', 'physical_feature_mismatches', 'cpu_orb_calls')):
        raise ValueError('Source/physical features were not verified')
    if not (run / 'NATIVE_COMPLETE').is_file() or not (run / 'tracking/map/EXPORT_COMPLETE').is_file():
        raise ValueError('Native drain and final map export completion required')
    mid = int((run / 'tracking/map/map_id.txt').read_text())
    if mid != continuity['maps_created'][0]['map_id']:
        raise ValueError('Export map differs from the only Atlas map')
    dense = result['dense']
    if dense['status'] != 'COMPLETED' or not dense.get('hardware_inference_verified'):
        raise ValueError('Actual DPU dense chain was not completed')
    proof = dict(result_sha256=digest(control / 'RESULT.json'), frames=len(frames),
                 first_valid_frame=first, last_source_frame=int(frames[-1]['source_frame_id']),
                 map_id=mid, continuity=continuity,
                 validity=checks['valid_after_initialization'], cpu_orb_calls=0,
                 original_result_status=result['status'],effective_acceptance_profile=profile,
                 user_review_sha256=digest(acceptance_review) if review else None)
    return result, proof


def create(run, camera, output, include_dense=True, acceptance_review=None):
    run, camera, output = (Path(p).resolve() for p in (run, camera, output))
    if output.exists(): raise ValueError('Fresh handoff directory required')
    result, proof = stable_source(run,acceptance_review)
    return _package_verified_source(run,camera,output,result,proof,include_dense,acceptance_review)


def _package_verified_source(run,camera,output,result,proof,include_dense=True,acceptance_review=None):
    """Shared file packaging only; each input kind must pass its own source gate."""
    if output.exists():raise ValueError('Fresh handoff directory required')
    source = run / 'tracking/map'
    before = {p.name: digest(p) for p in source.iterdir() if p.is_file()}
    output.mkdir(parents=True)
    try:
        (output/'MAPPING_RESULT.json').write_bytes((run.with_name(run.name+'_control')/'RESULT.json').read_bytes())
        if acceptance_review is not None:
            (output/'USER_ACCEPTANCE.json').write_bytes(Path(acceptance_review).read_bytes())
        selection = prepare(source, output / 'map')
        # seal checks float32 ORB-SLAM intrinsics before restoring shared camera
        # metadata; it never changes world coordinates or descriptor bytes.
        seal(output / 'map', camera, proof['map_id'])
        dense_points = 0
        if include_dense:
            from orb60.dense.ply import read_ply
            from orb60.demo_bridge.dense_environment import write, validate as validate_dense
            update = json.loads((run / 'dense/blocks/final_pose_update.json').read_text())
            if update['map_id'] != proof['map_id'] or not update['accepted']:
                raise ValueError('Final dense cloud is not attached to the exported map')
            xyz, rgb = read_ply(run / 'dense' / ('map_%d_dense.ply' % proof['map_id']))
            file = output / 'map/dense_environment.bin'
            write(file, xyz, rgb, output / 'map/points.csv', camera)
            dense_points = validate_dense(file, output / 'map/points.csv', camera)
            seal(output / 'map', camera, proof['map_id'])
        info = validate(output / 'map', camera.read_bytes())
        if before != {p.name: digest(p) for p in source.iterdir() if p.is_file()}:
            raise ValueError('Original optimized export changed during packaging')
        report = dict(status='SEALED_FOR_7015_NATIVE_IMPORT_NOT_INSTALLED', format='KV260_TO_7015_MAP_V1',
                      map=info, source=proof, selection=selection, dense_display_points=dense_points,
                      source_export_sha256=before,
                      scope='Sparse map geometry and real PL descriptors; native 7015 import/roundtrip and physical localization remain required',
                      files={p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*') if p.is_file()})
        (output / 'HANDOFF.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        archive = output / 'map_7015.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for p in sorted((output / 'map').iterdir()):
                if p.is_file():
                    item = tar.gettarinfo(str(p), arcname='map/' + p.name)
                    item.mode = 0o644
                    with p.open('rb') as stream: tar.addfile(item, stream)
        (output / 'TRANSFER.json').write_text(json.dumps(dict(archive=archive.name, sha256=digest(archive),
                  bytes=archive.stat().st_size, expected_map_version=info['version']), indent=2) + '\n')
        return report
    except BaseException as error:
        (output / 'FAILED.json').write_text(json.dumps(dict(error=repr(error))) + '\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'camera', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    dense_group=parser.add_mutually_exclusive_group()
    dense_group.add_argument('--include-dense',dest='include_dense',action='store_true',default=True,help='Include same-map RGB environment for7015 HDMI (default)')
    dense_group.add_argument('--sparse-only',dest='include_dense',action='store_false',help='Explicit sparse-only diagnostic; omits colored HDMI environment')
    parser.add_argument('--acceptance-review', type=Path,help='Exact result-bound explicit user tail-loss acceptance; original failed result remains immutable')
    r = create(**vars(parser.parse_args()))
    print(json.dumps(dict(status=r['status'], map=r['map'], dense_display_points=r['dense_display_points'])))
