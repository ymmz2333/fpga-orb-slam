"""Frozen source/feature validation; these tests do not emulate board hardware."""
from copy import deepcopy
import pytest
from orb60.kv260.run_network_system import check_frames


def sample():
    actual=[dict(source_frame_id=str(i),timestamp_ns=str(1000000000+i*33333333),
                 gray_crc=str(100+i),record_crc=str(200+i),count='280',
                 cpu_orb_calls='0',pose_valid='0' if i<2 else '1') for i in range(5)]
    identities=[{k:r[k] for k in ('source_frame_id','timestamp_ns','gray_crc')} for r in actual]
    return actual,identities,deepcopy(actual)


def test_identity_preserves_initialization_and_invalid_pose_statistics():
    a,b,c=sample();a[3]['pose_valid']='0'
    value=check_frames(a,b,c)
    assert value['first_valid_frame']==2 and value['valid_after_initialization']==2/3
    assert value['physical_feature_mismatches']==0


@pytest.mark.parametrize('field',('source_frame_id','timestamp_ns','gray_crc','record_crc','count','cpu_orb_calls'))
def test_corrupted_identity_feature_or_cpu_fallback_is_rejected(field):
    a,b,c=sample();a[3][field]=str(int(a[3][field])+1)
    with pytest.raises(ValueError):check_frames(a,b,c)


def test_missing_source_and_empty_tracking_are_rejected():
    a,b,c=sample()
    with pytest.raises(ValueError):check_frames(a[:-1],b,c)
    for r in a:r['pose_valid']='0'
    with pytest.raises(ValueError):check_frames(a,b,c)
