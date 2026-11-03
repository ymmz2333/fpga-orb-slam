import pytest
from orb60.kv260.ps.compile_keyframe_cadence import extract


SOURCE='''// retained license
#include "Tracking.h"
namespace ORB_SLAM3 {
bool Tracking::NeedNewKeyFrame()
{
    const bool c1a = mCurrentFrame.mnId>=mnLastKeyFrameId+mMaxFrames;
    const bool c1b = ((mCurrentFrame.mnId>=mnLastKeyFrameId+mMinFrames) && bLocalMappingIdle);
    return other_unchanged_inlier_and_recovery_conditions(c1a, c1b);
}
void Tracking::CreateNewKeyFrame() {}
}
'''


def test_only_minimum_monocular_idle_cadence_changes():
    private, original=extract(SOURCE,10)
    assert '// retained license' in private
    assert 'mCurrentFrame.mnId>=mnLastKeyFrameId+mMaxFrames' in private
    changed='mCurrentFrame.mnId>=mnLastKeyFrameId+(mSensor==System::MONOCULAR ? std::max(mMinFrames,10) : mMinFrames)'
    assert private.count(changed)==1
    assert original in private.replace(changed,'mCurrentFrame.mnId>=mnLastKeyFrameId+mMinFrames')


@pytest.mark.parametrize('source,interval',[(SOURCE,0),(SOURCE,True),(SOURCE,11),(SOURCE+SOURCE,10),
    (SOURCE.replace('mCurrentFrame.mnId>=mnLastKeyFrameId+mMinFrames','changed_upstream_policy'),10)])
def test_unsupported_policy_or_changed_source_is_rejected(source,interval):
    with pytest.raises(ValueError):extract(source,interval)
