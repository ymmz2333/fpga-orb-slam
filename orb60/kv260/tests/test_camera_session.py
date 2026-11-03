"""Offline orchestration/archive guards; these fixtures are not board results."""
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import numpy as np
import pytest
from orb60.demo_bridge.tests.offline_gate import bundle
from orb60.demo_bridge.map_bundle import seal,validate
from orb60.demo_bridge.dense_environment import write
from orb60.kv260.run_network_system import digest
from orb60.kv260.install_camera_map_7015 import check_handoff
from orb60.kv260 import run_camera_two_board_session as session


def fixture(root):
    camera=bundle(root/'map')
    write(root/'map/dense_environment.bin',np.array([[0,0,2],[1,0,2]]),np.array([[255,0,0],[0,255,0]]),root/'map/points.csv',camera)
    seal(root/'map',camera,7);info=validate(root/'map',camera.read_bytes())
    (root/'MAPPING_RESULT.json').write_text('{"fixture_only":true}')
    proof=dict(format='KV260_TO_7015_MAP_V1',map=info,dense_display_points=2,
               source=dict(format='KV260_LIVE_CAMERA_SOURCE_V1',camera_sha256=digest(camera),result_sha256=digest(root/'MAPPING_RESULT.json')))
    (root/'HANDOFF.json').write_text(json.dumps(proof))
    with tarfile.open(root/'map_7015.tar.gz','w:gz') as tar:
        for file in (root/'map').iterdir():tar.add(file,arcname='map/'+file.name)
    (root/'TRANSFER.json').write_text(json.dumps(dict(expected_map_version=info['version'],sha256=digest(root/'map_7015.tar.gz'))))
    return proof


@pytest.mark.parametrize('case',('valid','recorded_as_camera','explicit_recorded','wrong_source','wrong_source_camera','dense_count','escape','duplicate','changed_payload'))
def test_camera_install_requires_exact_bounded_colored_archive(tmp_path,case):
    proof=fixture(tmp_path);mode='live_camera'
    if case in ('recorded_as_camera','explicit_recorded'):
        proof['source'].pop('format')
        if case=='explicit_recorded':mode='recorded_diagnostic'
    if case=='wrong_source':(tmp_path/'MAPPING_RESULT.json').write_text('changed')
    if case=='wrong_source_camera':proof['source']['camera_sha256']='0'*64
    if case=='dense_count':proof['dense_display_points']=3
    if case in ('escape','duplicate','changed_payload'):
        archive=tmp_path/'map_7015.tar.gz'
        with tarfile.open(archive,'r:gz') as tar:entries=[(m,tar.extractfile(m).read()) for m in tar]
        if case=='escape':
            m=tarfile.TarInfo('../outside');m.size=1;entries.append((m,b'x'))
        if case=='duplicate':entries.append(entries[0])
        if case=='changed_payload':entries[0]=(entries[0][0],b'x'*entries[0][0].size)
        with tarfile.open(archive,'w:gz') as tar:
            for m,data in entries:tar.addfile(m,io.BytesIO(data))
        r=json.loads((tmp_path/'TRANSFER.json').read_text());r['sha256']=digest(archive)
        (tmp_path/'TRANSFER.json').write_text(json.dumps(r))
    (tmp_path/'HANDOFF.json').write_text(json.dumps(proof))
    if case in ('valid','explicit_recorded'):assert check_handoff(tmp_path,mode)[2]['map_id']==7
    else:
        with pytest.raises(ValueError):check_handoff(tmp_path,mode)


def test_no_map_finishes_before_any_handoff_or_localization(tmp_path,monkeypatch):
    from orb60.kv260 import run_camera_system,handoff_camera_7015
    config=tmp_path/'config.json';config.write_text(json.dumps(dict(root=str(tmp_path))))
    connection=tmp_path/'connection.json';connection.write_text('{}')
    library=tmp_path/'lib.so';library.write_bytes(b'fixture only')
    monkeypatch.setattr(session.platform,'machine',lambda:'aarch64');monkeypatch.setattr(session,'sys',SimpleNamespace(platform='linux'))
    monkeypatch.setattr(session,'network_snapshot',lambda p:p.write_text('{"fixture_only":true}'))
    def mapped(config,output,frames):
        control=output.with_name(output.name+'_control');control.mkdir()
        (control/'RESULT.json').write_text(json.dumps(dict(status='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED')))
        return 0
    monkeypatch.setattr(run_camera_system,'run',mapped)
    monkeypatch.setattr(handoff_camera_7015,'create',lambda *a,**k:pytest.fail('Uninitialized camera was handed off'))
    out=tmp_path/'session'
    assert session.run(config,connection,library,out,frames=2,localization_frames=2)==2
    assert json.loads((out/'session.json').read_text())['status']=='CAMERA_INPUT_COMPLETE_NO_MAP_NO_HANDOFF'
    assert not (out/'handoff').exists() and not (out/'localization').exists()


def test_camera_diagnostic_import_requires_explicit_selection(tmp_path):
    proof=fixture(tmp_path)
    proof['source'].update(format='KV260_LIVE_CAMERA_DIAGNOSTIC_SOURCE_V1',
                           diagnostic_only=True,stability_accepted=False)
    (tmp_path/'HANDOFF.json').write_text(json.dumps(proof))
    with pytest.raises(ValueError):check_handoff(tmp_path)
    checked=check_handoff(tmp_path,allow_camera_diagnostic=True)
    assert checked[0]['source']['diagnostic_only'] and not checked[0]['source']['stability_accepted']


@pytest.mark.parametrize('changed',('none','payload','selection','manual'))
def test_manual_current_map_import_is_explicit_and_keeps_archive_checks(tmp_path,changed):
    proof=fixture(tmp_path)
    proof['source'].update(format='KV260_MANUAL_LATEST_MAP_SOURCE_V1',manual_control=True,
                           single_map_required=False,map_selection='Atlas current map at completed shutdown')
    if changed=='payload':(tmp_path/'map/points.csv').write_bytes(b'corrupt')
    if changed=='selection':proof['source']['map_selection']='largest map'
    if changed=='manual':proof['source']['manual_control']=False
    (tmp_path/'HANDOFF.json').write_text(json.dumps(proof))
    with pytest.raises(ValueError):check_handoff(tmp_path)
    if changed=='none':assert check_handoff(tmp_path,allow_manual_latest=True)[2]['map_id']==7
    else:
        with pytest.raises(ValueError):check_handoff(tmp_path,allow_manual_latest=True)
