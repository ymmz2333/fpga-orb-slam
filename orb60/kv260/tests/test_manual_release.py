import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from orb60.kv260.install_camera_map_7015 import require_space,reuse
from orb60.kv260.manual_restart import request,run


def test_space_measurement_refuses_full_or_unparseable_volume(tmp_path):
    b=Mock(output=tmp_path)
    p=tmp_path/'free_space.stdout.log'
    for value in ('0','32767','error'):
        p.write_text(value)
        with pytest.raises((RuntimeError,ValueError)):require_space(b)
    p.write_text('65536');assert require_space(b)==64*2**20
    with pytest.raises(RuntimeError):require_space(b,40*2**20)


def test_reuse_requires_exact_map_binary_camera_and_original_manifest(tmp_path,monkeypatch):
    import orb60.kv260.install_camera_map_7015 as m
    b=Mock(output=tmp_path,connection=dict(network_localizer_sha256='a'*64,map_importer_sha256='b'*64))
    monkeypatch.setattr(m,'check_handoff',Mock(return_value=({},dict(sha256='c'*64),dict(version='d'*64))))
    monkeypatch.setattr(m,'digest',lambda _: 'e'*64)
    monkeypatch.setattr(m,'require_space',Mock())
    receipt=dict(status='IMPORTED',release='/opt/orb-demo/kv260_network_camera_manual_test',version='d'*64,
        archive_sha256='c'*64,calibration_sha256='e'*64,native_sha256='a'*64,importer_sha256='b'*64,manifest_sha256='f'*64)
    assert reuse(b,tmp_path,dict(receipt,version='1'*64)) is None
    assert reuse(b,tmp_path,dict(receipt,release='/tmp/evil')) is None
    b.run.assert_not_called()
    (tmp_path/'reuse_map.stdout.log').write_text('MAP_RELEASE_MISSING\n');assert reuse(b,tmp_path,receipt) is None
    (tmp_path/'reuse_map.stdout.log').write_text('INSTALLED_MAP_REUSE_VERIFIED\n')
    result=reuse(b,tmp_path,receipt)
    assert result['reuse_verified'] and result['release']==receipt['release']
    script=b.run.call_args.args[0]
    assert 'sha256sum -c SHA256SUMS' in script and 'cmp maps_live/' in script
    assert 'cp ' not in script and 'tar ' not in script and 'mkdir ' not in script
    b.run.side_effect=RuntimeError('hash mismatch')
    with pytest.raises(RuntimeError,match='hash mismatch'):reuse(b,tmp_path,receipt)


def test_restart_request_survives_service_exit_without_sudo_or_shell(tmp_path,monkeypatch):
    call=Mock();monkeypatch.setattr('orb60.kv260.manual_restart.subprocess.run',call)
    p=request(tmp_path,123)
    assert json.loads(p.read_text())['status']=='QUEUED'
    args=call.call_args.args[0]
    assert args[:3]==['systemd-run','--user','--collect'] and '--gui-pid' in args
    assert not call.call_args.kwargs.get('shell') and 'sudo' not in args


def test_restart_rejects_unowned_report_before_touching_services(tmp_path,monkeypatch):
    call=Mock();monkeypatch.setattr('orb60.kv260.manual_restart.subprocess.run',call)
    with pytest.raises(ValueError):run(tmp_path,tmp_path/'outside.json',123)
    call.assert_not_called()
