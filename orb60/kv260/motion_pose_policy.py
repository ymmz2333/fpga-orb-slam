"""Explicit PS algorithm candidate; final geometry gates remain mandatory."""
import json
from pathlib import Path
BUILD_STATUS='NATIVE_DEFER_STRONG_MOTION_CANDIDATE_PASS'


def validate(config,build_status):
    mode=config.get('motion_pose_policy','original')
    if mode not in ('original','defer-strong'):raise ValueError('Explicit motion pose policy required')
    if mode!='original' and build_status!=BUILD_STATUS:raise ValueError('Motion pose policy requires its private native candidate')
    return mode


def check(path,frames):
    p=json.loads(Path(path).read_text())
    if p.get('status')!='MOTION_POSE_COUNTERS_RECORDED' or p.get('policy')!='defer-strong' or p.get('pending') is not False or p.get('minimum_projected_matches')!=100 or p.get('minimum_previous_inliers')!=80:raise ValueError('Motion pose counters/guards invalid')
    for k in ('motion_calls','deferred','finalized','local_solves'):
        if type(p.get(k)) is not int or not 0<=p[k]<=frames:raise ValueError('Motion pose counter out of bounds')
    if not 0<p['deferred']==p['finalized']<=p['motion_calls'] or p['local_solves']<p['finalized']:raise ValueError('Deferred frame missing unchanged final pose solve')
    p['verification']='EVERY_DEFERRED_FRAME_RECEIVED_ORIGINAL_FINAL_POSE_SOLVE'
    return p
