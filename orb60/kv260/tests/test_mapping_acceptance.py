import pytest
from orb60.kv260.mapping_acceptance import evaluate

def check(profile='stable_map_handoff',ratio=1.,continuity='SINGLE_MAP_CREATION_PASS',**kwargs):
    return evaluate(profile,dict(valid_after_initialization=ratio),dict(status=continuity),dict(all_geometry_fps=15.),
                    profiling=kwargs.get('profiling',False),kernel_tainted=kwargs.get('taint',13312),last_pose_valid=kwargs.get('last',True))

def test_current_stability_goal_is_separate_from_old_performance_trials():
    assert check()['status']=='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS'
    assert check('throughput30')['status']=='FAILED_TARGET_GATES'

@pytest.mark.parametrize('changes',[{'ratio':.97},{'continuity':'MAP_CONTINUITY_FAILED'},{'last':False},{'profiling':True},{'taint':13440}])
def test_stable_profile_preserves_physical_quality_gates(changes):
    assert check(**changes)['status']=='FAILED_TARGET_GATES'

def test_unknown_profile_does_not_disable_gates():
    with pytest.raises(ValueError):check('anything')

@pytest.mark.parametrize('fps,passed',[(4.99,False),(5.,True),(10.,True)])
def test_practical_speed_profile_keeps_a_real_five_fps_floor(fps,passed):
    result=evaluate('stable_map_5fps',dict(valid_after_initialization=1.),dict(status='SINGLE_MAP_CREATION_PASS'),
                    dict(all_geometry_fps=fps),profiling=False,kernel_tainted=13312,last_pose_valid=True)
    assert (result['status']=='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS')==passed

def test_new_speed_profile_still_requires_valid_last_pose():
    assert check('stable_map_5fps',last=False)['status']=='FAILED_TARGET_GATES'

@pytest.mark.parametrize('segments,passed',[
    ([dict(first_source_frame=2213,last_source_frame=2296,frames=84)],True),
    ([dict(first_source_frame=2212,last_source_frame=2296,frames=85)],False),
    ([dict(first_source_frame=100,last_source_frame=183,frames=84)],False),
    ([dict(first_source_frame=100,last_source_frame=100,frames=1),dict(first_source_frame=2214,last_source_frame=2296,frames=83)],False)])
def test_user_accepted_tail_does_not_allow_other_loss_patterns(segments,passed):
    r=evaluate('stable_map_5fps_tail84',dict(frames=2297,valid_after_initialization=2073/2157),
               dict(status='SINGLE_MAP_CREATION_PASS',tracking_loss_segments=segments),
               dict(all_geometry_fps=13.385),profiling=False,kernel_tainted=13312,last_pose_valid=False)
    assert (r['status']=='ACTUAL_STABLE_MAP_DPU_GPU_COMPONENT_PASS')==passed
