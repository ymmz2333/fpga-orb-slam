import pytest
from orb60.kv260.ps.compose_bounded_mapping import transform
from orb60.kv260.tests.test_packed_mapper import ENTRY


def test_publication_wait_replaces_only_the_scheduling_contract():
    value=transform('#include "System.h"\n'+ENTRY)
    assert value.count('KvMapperProgress::wait(10000)')==1
    assert 'WaitForLocalMapping' not in value
    assert '(mapper_barrier?"published":"none")' in value
    assert 'auto pose=slam.TrackMonocular(original_gray,original_timestamp);' in value
    assert 'require(original_feature_crc==physical_feature_crc,"unchanged check");' in value
    assert 'map_sync_ms\\n' in value


def test_unreviewed_entry_include_is_rejected():
    with pytest.raises(ValueError):transform(ENTRY)
