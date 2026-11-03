import json
import pytest
from orb60.kv260.dense_service import DpuDepth
from orb60.kv260.run_network_system import digest


def config(tmp):
    for name in ('model','preflight','placement'):(tmp/name).write_bytes(b'component-test-only')
    selection=tmp/'selection.json';selection.write_text(json.dumps(dict(user_visual_acceptance=True,target_model_sha256=digest(tmp/'model'))))
    return {**{n:str(tmp/n) for n in ('model','preflight','placement')},'selection':str(selection)}


def test_explicit_empty_camera_does_not_start_fake_or_empty_worker(tmp_path,monkeypatch):
    c=config(tmp_path);c.update(input_kind='live_camera',allow_uninitialized_camera_completion=True,defer_worker_until_first_keyframe=True)
    def forbidden(*a,**k):raise AssertionError('No worker should be spawned before a real selected keyframe')
    monkeypatch.setattr('orb60.kv260.dense_service.subprocess.Popen',forbidden)
    folder=tmp_path/'depth_run';folder.mkdir();engine=DpuDepth(c,folder)
    assert engine.worker is None;engine.close()
    assert not (folder/'depth/worker.json').exists()


def test_deferred_option_cannot_change_production_path_without_camera_scope(tmp_path):
    c=config(tmp_path);c['defer_worker_until_first_keyframe']=True
    folder=tmp_path/'depth_run';folder.mkdir()
    with pytest.raises(ValueError,match='live-camera'):DpuDepth(c,folder)
