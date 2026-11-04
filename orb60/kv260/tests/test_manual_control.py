import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from orb60.kv260.manual_control import Session,allowed,submit
from orb60.kv260.ps.build_manual_camera_entry import transform


def test_manual_entry_has_no_frame_limit_and_keeps_solver_and_final_export():
    from orb60.kv260.ps.build_camera_entry import transform as finite
    base=(Path(__file__).parent/'fixtures/retained_packed_camera_base.cc').read_text()
    text=transform(finite(base))
    assert 'for(size_t i=0;;++i)' in text and 'OPERATOR_STOP_DRAINED' in text
    assert 'input.requestStop();input.joinProducer()' in text and 'final_frame,&raw.keys' in text
    assert 'slam.TrackMonocular(f.gray,double(f.id.stamp)*1e-9)' in text
    assert text.index('input.finish()')<text.index('slam.Shutdown()')<text.index('slam.ExportBridgeMap')
    with pytest.raises(ValueError):transform(text)


def test_buttons_allow_new_scan_from_localization_but_prevent_overlap():
    assert allowed('IDLE',False)['start_mapping']
    assert allowed('LOCALIZING',True)['start_mapping']
    assert 'stop_localization' not in allowed('LOCALIZING',True)
    for phase in ('STARTING_MAP','MAPPING','SAVING','STARTING_LOCAL','STOPPING_LOCAL'):
        assert not allowed(phase,True)['start_mapping']
    assert allowed('STARTING_MAP',False)['stop_mapping']


def fixture(tmp_path):
    s=Session.__new__(Session)
    s.folder=tmp_path;s.root=tmp_path;s.phase='MAPPING';s.handoff=None;s.message='';s.events=[];s.run=tmp_path/'mapping'
    s.job=Mock();s.job.poll.return_value=None;s.log=Mock();s.kind='mapping';s.counter=1;s.quitting=False;s.processed=set()
    s.stop_file=tmp_path/'stop';s.stop_pending=False;s.pending_mapping=False
    return s


def test_stop_during_startup_is_queued_until_native_fresh_path_check_passes(tmp_path):
    s=fixture(tmp_path);s.phase='STARTING_MAP';s.action('stop_mapping');s.tick()
    assert s.phase=='SAVING' and not s.stop_file.exists()
    control=tmp_path/'mapping_control';control.mkdir();(control/'RESULT.json').write_text('{}')
    s.tick();assert s.stop_file.exists()


def test_stopped_uninitialized_camera_does_not_switch_or_install(tmp_path):
    s=fixture(tmp_path);s.stop_pending=True;s.phase='SAVING';s.job.poll.return_value=0
    control=tmp_path/'mapping_control';control.mkdir()
    (control/'RESULT.json').write_text(json.dumps(dict(status='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED')))
    s.tick();assert s.phase=='IDLE' and s.job is None and s.handoff is None
    assert not (tmp_path/'handoff_001').exists()


def test_unexpected_job_exit_is_failure_not_operator_completion(tmp_path):
    s=fixture(tmp_path);s.job.poll.return_value=1;s.tick()
    assert s.phase=='ERROR' and not s.handoff


def test_quit_during_mapping_waits_for_save_instead_of_killing(tmp_path):
    s=fixture(tmp_path);job=s.job;s.action('quit');s.tick()
    assert s.phase=='SAVING' and s.quitting and s.job is job
    job.terminate.assert_not_called();job.kill.assert_not_called()


def test_restart_shutdown_retains_failed_result_and_last_map(tmp_path):
    s=fixture(tmp_path);s.stop_pending=True;s.quitting=True;s.job.poll.return_value=1;s.handoff=tmp_path/'old'
    control=tmp_path/'mapping_control';control.mkdir();result=control/'RESULT.json'
    result.write_text(json.dumps(dict(status='FAILED',error='full disk')))
    s.tick()
    assert s.phase=='CLOSED' and s.handoff==tmp_path/'old'
    assert json.loads(result.read_text())['status']=='FAILED' and 'full disk' in s.message


def test_submit_cannot_create_controller_directory_or_send_unknown_action(tmp_path):
    target=tmp_path/'new'
    with pytest.raises(FileNotFoundError):submit(target,'quit')
    assert not target.exists()
    with pytest.raises(ValueError):submit(tmp_path,'automatic_transition')


def test_failed_start_recovers_error_buttons_instead_of_stuck_starting(tmp_path):
    s=fixture(tmp_path);s.job=None;s.phase='STARTING_LOCAL'
    s.action=Mock(side_effect=ValueError('map transfer failed'))
    s.command('start_localization')
    assert s.phase=='ERROR' and s.message=='map transfer failed'
    assert allowed(s.phase,False)['start_mapping']


def test_localization_fault_is_not_reported_as_saved_success(tmp_path):
    s=fixture(tmp_path);s.kind='localization';s.stop_pending=True;s.job.poll.return_value=1;s.phase='STOPPING_LOCAL'
    s.run.mkdir();(s.run/'RESULT.json').write_text(json.dumps(dict(status='FAILED',operator_stop_requested=True,error='Physical PL fault')))
    s.tick();assert s.phase=='ERROR' and 'PL fault' in s.message


def test_end_mapping_automatically_uses_new_current_map(tmp_path,monkeypatch):
    s=fixture(tmp_path);s.stop_pending=True;s.phase='SAVING';s.job.poll.return_value=0
    s.config={'camera':'camera.csv'};s.start_localization=Mock()
    control=tmp_path/'mapping_control';control.mkdir()
    (control/'RESULT.json').write_text(json.dumps(dict(status='FAILED_TARGET_GATES')))
    create=Mock(return_value=dict(source=dict(camera_sha256='a'*64,map_id=1,failed_gates=['multiple maps'])))
    monkeypatch.setattr('orb60.kv260.handoff_camera_7015.create',create)
    s.tick()
    assert s.handoff==tmp_path/'handoff_001'
    assert create.call_args.kwargs=={'manual_latest':True}
    s.start_localization.assert_called_once()
    assert json.loads((tmp_path/'manual_latest_map.json').read_text())['handoff']==str(s.handoff)


def test_new_mapping_waits_for_localization_eos_and_drain(tmp_path):
    s=fixture(tmp_path);s.kind='localization';s.phase='LOCALIZING';s.handoff=tmp_path/'old'
    s.start_mapping=Mock();s.action('start_mapping')
    assert s.pending_mapping and s.stop_pending and s.phase=='STOPPING_LOCAL'
    s.start_mapping.assert_not_called();s.job.kill.assert_not_called()
    s.run.mkdir();(s.run/'RESULT.json').write_text(json.dumps(dict(
        status='ACTUAL_7015_NATIVE_NETWORK_COLOR_LOCALIZATION_COMPONENT_PASS',operator_stop_requested=True,valid_poses=12)))
    s.job.poll.return_value=0;s.tick();s.start_mapping.assert_called_once()


def test_uninitialized_new_scan_resumes_existing_map(tmp_path):
    s=fixture(tmp_path);s.stop_pending=True;s.job.poll.return_value=0;s.handoff=tmp_path/'old';s.start_localization=Mock()
    control=tmp_path/'mapping_control';control.mkdir()
    (control/'RESULT.json').write_text(json.dumps(dict(status='ACTUAL_CAMERA_SYSTEM_COMPONENT_PASS_NO_MAP_INITIALIZED')))
    s.tick();s.start_localization.assert_called_once();assert s.handoff==tmp_path/'old'


@pytest.mark.parametrize('error',[json.JSONDecodeError('empty','',0),FileNotFoundError('missing archive'),ValueError('camera mismatch')])
def test_bad_saved_map_keeps_controller_alive_without_starting_localization(tmp_path,monkeypatch,error):
    config=tmp_path/'config.json';config.write_text(json.dumps(dict(root=str(tmp_path),camera='camera.csv')))
    connection=tmp_path/'connection.json';connection.write_text('{}')
    monkeypatch.setattr('orb60.kv260.peer_link.PeerLink',Mock())
    monkeypatch.setattr('orb60.kv260.install_camera_map_7015.check_handoff',Mock(side_effect=error))
    saved=tmp_path/'bad_map';saved.mkdir();(saved/'HANDOFF.json').write_bytes(b'')
    app=Session(config,connection,tmp_path/'library',tmp_path/'session',saved)
    app.start_localization=Mock();app.resume()
    assert app.phase=='ERROR' and app.handoff is None
    app.start_localization.assert_not_called()
    state=json.loads((app.folder/'status.json').read_text())
    assert state['buttons']['start_mapping'] and not state['map_available']
    assert state['events'][-1]['event']=='SAVED_MAP_REJECTED'
    assert (saved/'HANDOFF.json').read_bytes()==b''


def test_failed_map_flush_does_not_replace_last_selection(tmp_path,monkeypatch):
    from orb60.kv260.saved_map import commit_selection
    pointer=tmp_path/'manual_latest_map.json';pointer.write_text('{"handoff":"old"}')
    handoff=tmp_path/'new';handoff.mkdir();(handoff/'map.bin').write_bytes(b'map')
    monkeypatch.setattr('orb60.kv260.saved_map.os.fsync',Mock(side_effect=OSError('write failed')))
    with pytest.raises(OSError):commit_selection(tmp_path,handoff,'a'*64)
    assert json.loads(pointer.read_text())=={'handoff':'old'}
