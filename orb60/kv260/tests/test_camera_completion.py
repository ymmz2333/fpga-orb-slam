import json
import pytest
from orb60.kv260.camera_completion import uninitialized_camera


def setup(root):
    (root/'dense/color_poses').mkdir(parents=True)
    mapping=dict(status='CAMERA_TRACKING_DRAINED_EXPORT_PENDING',source_input='actual_KV260_V4L2_camera',
                 frames=300,valid_poses=0,selected_keyframes=0,cpu_orb_calls=0)
    state=dict(status='INPUT_DRAINED_NO_MAP_INITIALIZED',mapping_verified=False)
    (root/'network_mapping.json').write_text(json.dumps(mapping));(root/'camera_mapping_status.json').write_text(json.dumps(state))
    (root/'CAMERA_INPUT_COMPLETE').touch()
    return dict(input_kind='live_camera',allow_uninitialized_camera_completion=True),mapping


def test_old_production_path_does_not_accept_empty_camera(tmp_path):
    assert not uninitialized_camera({},tmp_path,set(),{})


def test_explicit_no_map_input_can_drain_without_claiming_depth(tmp_path):
    c,m=setup(tmp_path)
    assert uninitialized_camera(c,tmp_path,set(),{})


@pytest.mark.parametrize('case',('video','fake_pose','fake_keyframe','cpu','fake_complete','pose_file','processed_depth','block','wrong_input','missing_drain'))
def test_no_map_path_rejects_contradictory_proof(tmp_path,case):
    c,m=setup(tmp_path);seen=set();blocks={}
    if case=='video':c['input_kind']='saved_video'
    if case=='fake_pose':m['valid_poses']=1
    if case=='fake_keyframe':m['selected_keyframes']=1
    if case=='cpu':m['cpu_orb_calls']=1
    if case=='wrong_input':m['source_input']='saved_video'
    if case=='fake_complete':(tmp_path/'NATIVE_COMPLETE').touch()
    if case=='pose_file':(tmp_path/'dense/color_poses/f0.json').write_text('{}')
    if case=='processed_depth':seen.add('f0.json')
    if case=='block':blocks[0]=object()
    if case=='missing_drain':(tmp_path/'CAMERA_INPUT_COMPLETE').unlink()
    (tmp_path/'network_mapping.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):uninitialized_camera(c,tmp_path,seen,blocks)
