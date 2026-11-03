import json
import pytest
from orb60.kv260.motion_pose_policy import BUILD_STATUS,validate,check
from orb60.kv260.ps.motion_pose_transform import transform


def test_policy_requires_its_native_candidate():
    assert validate({},'NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS')=='original'
    assert validate({'motion_pose_policy':'defer-strong'},BUILD_STATUS)=='defer-strong'
    with pytest.raises(ValueError):validate({'motion_pose_policy':'defer-strong'},'NATIVE_FRAME_MOVE_PACKED_BMP_COMPONENT_PASS')


@pytest.mark.parametrize('change',[{}, {'finalized':2},{'pending':True},{'deferred':0},{'local_solves':2},{'motion_calls':2},{'deferred':True},{'minimum_projected_matches':20}])
def test_all_deferred_frames_require_real_final_solves(tmp_path,change):
    p=dict(status='MOTION_POSE_COUNTERS_RECORDED',policy='defer-strong',motion_calls=8,deferred=3,finalized=3,local_solves=9,pending=False,minimum_projected_matches=100,minimum_previous_inliers=80)
    p.update(change);f=tmp_path/'policy.json';f.write_text(json.dumps(p))
    if not change:assert check(f,10)['finalized']==3
    else:
        with pytest.raises(ValueError):check(f,10)


def test_transform_preserves_final_geometry_and_default_path():
    source='''bool Tracking::TrackWithMotionModel()
{
    if(nmatches<20)return false;
    Optimizer::PoseOptimization(&mCurrentFrame);
    return nmatchesMap>=10;
}
bool Tracking::TrackLocalMap()
{
    if (!mpAtlas->isImuInitialized())
        Optimizer::PoseOptimization(&mCurrentFrame);
    else
        inertial();
    return mnMatchesInliers>=30;
}
'''
    private=transform(source)
    assert 'return mnMatchesInliers>=30;' in private and 'return nmatchesMap>=10;' in private
    assert 'KvMotionPose::final_pose(mCurrentFrame.mnId)' in private
    with pytest.raises(ValueError):transform(source.replace('Optimizer::PoseOptimization(&mCurrentFrame);','different_solver();'))
