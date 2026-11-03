"""Camera integration retains solver/physical PL and separates no-map completion."""
from pathlib import Path
import pytest
from orb60.kv260.ps.build_camera_entry import transform


BASE=(Path(__file__).parent/'fixtures/retained_packed_camera_base.cc').read_text()


def test_camera_replaces_only_input_identity_and_final_status():
    value=transform(BASE)
    for line in ('auto pose=slam.TrackMonocular(f.gray,double(f.id.stamp)*1e-9);',
                 'const double map_sync_ms=mapper_barrier?KvMapperProgress::wait(10000):0;',
                 'raw.timestamp==f.id.stamp&&raw.count==unsigned(stats.count)',
                 'publish_rgb(f,out+"/dense/rgb_cache")'):
        assert line in value
    assert 'KvNetwork::CameraPipeline input' in value
    assert 'KvNetwork::identities(' not in value and 'VideoPipeline input' not in value
    assert 'camera_frames.csv' in value and 'capture_sequence' in value
    assert 'INPUT_DRAINED_NO_MAP_INITIALIZED' in value
    assert value.index('if(!valid)')<value.index('slam.ExportBridgeMap')<value.index('out+"/NATIVE_COMPLETE"')
    assert 'mapping_verified\\":false' in value
    assert 'camera_original_Y' in value and 'actual_KV260_V4L2_camera' in value


@pytest.mark.parametrize('change',('duplicate','math','feature_identity','already_applied'))
def test_unreviewed_camera_entry_or_solver_changes_rejected(change):
    source=BASE
    if change=='duplicate':source+=BASE
    if change=='math':source=source.replace('TrackMonocular(f.gray','TrackMonocular(other.gray')
    if change=='feature_identity':source=source.replace('raw.timestamp==f.id.stamp','raw.timestamp>0')
    if change=='already_applied':source=transform(source)
    with pytest.raises(ValueError):transform(source)
