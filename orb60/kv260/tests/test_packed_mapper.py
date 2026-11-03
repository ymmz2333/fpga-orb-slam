"""Scheduling edits must retain the original input, pose and feature checks."""
import pytest
from orb60.kv260.ps.compose_packed_mapper import transform


ENTRY = '''int main() {
    int tracking_core=-1; // retained input and CPU policy
    journal<<"engine_ns,track_cpu_ms\\n";
    auto pose=slam.TrackMonocular(original_gray,original_timestamp);
            auto stats=FeatureIO::Stats();auto& raw=KvNetwork::current();
    require(original_feature_crc==physical_feature_crc,"unchanged check");
    journal<<cpu_ms<<'\\n';
    result<<"unchanged"
      <<",\\\"tracking_cpu_core\\\":"<<tracking_core;
}
'''


def test_scheduling_retains_original_math_and_reports_its_wait():
    value = transform(ENTRY)
    assert 'auto pose=slam.TrackMonocular(original_gray,original_timestamp);' in value
    assert 'require(original_feature_crc==physical_feature_crc,"unchanged check");' in value
    assert value.count('WaitForLocalMapping(10000)') == 1
    assert 'map_sync_ms\\n' in value and "<<cpu_ms<<','<<map_sync_ms" in value
    assert 'mapper_wait_mode' in value and 'mapper_barrier' in value


@pytest.mark.parametrize('entry', [ENTRY + ENTRY, ENTRY.replace('auto stats=', 'auto changed_stats=')])
def test_unreviewed_or_duplicate_scheduling_boundaries_fail(entry):
    with pytest.raises(ValueError):
        transform(entry)


def test_applying_the_scheduling_edit_twice_is_rejected():
    with pytest.raises(ValueError):
        transform(transform(ENTRY))
